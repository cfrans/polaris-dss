"""Endpoints da API.

As rotas orquestram e traduzem; a decisão de negócio fica em `engine/service.py`. Em especial, é o
serviço — e não esta camada — que impõe a exigência de aprovação humana antes de qualquer execução.

Os manipuladores são funções síncronas de propósito: o driver do PostgreSQL é síncrono, e o FastAPI
executa rotas `def` numa pool de threads. Declará-las `async def` bloquearia o laço de eventos.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from ..db import queries
from ..db.connection import conectar
from ..engine.knowledge_base import KnowledgeBaseError
from ..engine.knowledge_base import load as carregar_kb
from ..engine.models import Alert
from ..engine.zabbix_client import normalizar_webhook
from ..engine.service import (
    ExecucaoNaoAutorizadaError,
    ExecutorSimulado,
    decidir,
    executar,
    exibir,
    ingerir,
)
from .schemas import (
    AlertaSimulado,
    EventoZabbix,
    DecisaoRequest,
    DecisaoResponse,
    IncidenteDetalhe,
    IncidenteResumo,
    IngestaoResponse,
    ListaIncidentes,
    ResultadoResponse,
    Saude,
)

router = APIRouter()
VERSAO_API = "0.4.0"


def get_conn():
    with conectar() as conexao:
        yield conexao


def _erro(status: int, codigo: str, mensagem: str, **detalhes: Any) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"erro": codigo, "mensagem": mensagem, "detalhes": detalhes},
    )


# ---------------------------------------------------------------------------
# Ingestão
# ---------------------------------------------------------------------------


@router.post("/webhook/zabbix", response_model=IngestaoResponse, status_code=201,
             tags=["ingestão"])
def webhook_zabbix(
    request: Request,
    corpo: EventoZabbix,
    conn=Depends(get_conn),
    x_polaris_token: str = Header(default=""),
) -> IngestaoResponse:
    """Recebe o evento empurrado pela Action do Zabbix.

    Analisa, calcula a confiança e persiste como pendente. Não executa nada: a remediação depende
    da decisão humana registrada em seguida.
    """
    esperado = request.app.state.settings.polaris_webhook_token
    if not esperado:
        raise _erro(503, "webhook_nao_configurado",
                    "POLARIS_WEBHOOK_TOKEN não definido; a recepção de eventos está desabilitada.")
    if not secrets.compare_digest(x_polaris_token, esperado):
        raise _erro(401, "token_invalido", "Header X-Polaris-Token ausente ou inválido.")

    alerta = normalizar_webhook(corpo.model_dump())
    if not alerta.hostname:
        raise _erro(400, "evento_incompleto", "O evento não informa o host de origem.")

    ingestao = ingerir(conn, alerta, request.app.state.kb, request.app.state.config)

    if ingestao.duplicado:
        return IngestaoResponse(status="duplicate", incidente_id=ingestao.incidente_id)
    if ingestao.sem_regra:
        return IngestaoResponse(
            status="no_match",
            incidente_id=ingestao.incidente_id,
            motivo=f"nenhuma regra compatível com tipo_alerta={alerta.tipo_alerta}",
        )

    s = ingestao.sugestao
    return IngestaoResponse(status="created", incidente_id=ingestao.incidente_id,
                            regra=s.rule.id, confianca=s.confianca, banda=s.banda.value)


# ---------------------------------------------------------------------------
# Incidentes
# ---------------------------------------------------------------------------


@router.get("/api/v1/incidentes", response_model=ListaIncidentes, tags=["incidentes"])
def listar(
    request: Request,
    status: str | None = Query(default="pendente"),
    limit: int = Query(default=50, ge=1, le=500),
    conn=Depends(get_conn),
) -> ListaIncidentes:
    kb = request.app.state.kb
    linhas = queries.listar_incidentes(conn, status=status or None, limite=limit)
    itens = [
        IncidenteResumo(
            id=l["id"],
            id_evento=l["id_evento"],
            hostname=l["hostname"],
            severidade=l["severidade"],
            regra=l["regra_disparada"],
            nome_regra=(r.nome if (r := kb.por_id(l["regra_disparada"] or "")) else None),
            confianca=float(l["confianca_calculada"]) if l["confianca_calculada"] else None,
            banda=l["banda_confianca"],
            status=l["status_execucao"],
            ts_criacao=l["ts_criacao"],
        )
        for l in linhas
    ]
    return ListaIncidentes(total=len(itens), itens=itens)


@router.get("/api/v1/incidentes/{incidente_id}", response_model=IncidenteDetalhe,
            tags=["incidentes"])
def detalhar(request: Request, incidente_id: int, conn=Depends(get_conn)) -> IncidenteDetalhe:
    registro = queries.obter_incidente(conn, incidente_id)
    if registro is None:
        raise _erro(404, "incidente_inexistente", f"Incidente {incidente_id} não encontrado.")

    kb = request.app.state.kb
    regra = kb.por_id(registro["regra_disparada"] or "")
    trace = registro["explicabilidade"] or {}

    return IncidenteDetalhe(
        id=registro["id"],
        id_evento=registro["id_evento"],
        hostname=registro["hostname"],
        severidade=registro["severidade"],
        status=registro["status_execucao"],
        regra=registro["regra_disparada"],
        nome_regra=regra.nome if regra else trace.get("nome_regra"),
        diagnostico=regra.diagnostico if regra else None,
        comando=registro["comando_executado"],
        rollback=regra.render(regra.remediacao.rollback) if regra else None,
        destrutiva=regra.remediacao.destrutiva if regra else False,
        timeout_segundos=regra.remediacao.timeout_segundos if regra else None,
        confianca=float(registro["confianca_calculada"]) if registro["confianca_calculada"] else None,
        banda=registro["banda_confianca"],
        evidencias=trace.get("evidencias"),
        fatores=trace.get("fatores", []),
        candidatas_descartadas=trace.get("regras_candidatas_descartadas", []),
        versao_kb=registro["versao_kb"],
        versao_motor=registro["versao_motor"],
        decisao_humana=registro["decisao_humana"],
        operador=registro["operador"],
        motivo_rejeicao=registro["motivo_rejeicao"],
        exit_code=registro["exit_code"],
        output=registro["output_execucao"],
        erro_execucao=registro["output_erro"],
        ts_deteccao=registro["ts_deteccao"],
        ts_criacao=registro["ts_criacao"],
        ts_exibicao=registro["ts_exibicao"],
        ts_aprovacao=registro["ts_aprovacao"],
        ts_conclusao=registro["ts_conclusao"],
    )


@router.patch("/api/v1/incidentes/{incidente_id}/exibicao", tags=["incidentes"])
def marcar_exibicao(incidente_id: int, conn=Depends(get_conn)) -> dict[str, Any]:
    """Registra o instante em que a interface apresentou o incidente ao operador.

    Sem este marco não existe tempo de decisão humana, e sem ele o MTTR não pode ser decomposto —
    que é a análise mais informativa do experimento. A interface é obrigada a chamar este endpoint.
    """
    if queries.obter_incidente(conn, incidente_id) is None:
        raise _erro(404, "incidente_inexistente", f"Incidente {incidente_id} não encontrado.")
    primeira_vez = exibir(conn, incidente_id)
    return {"status": "registrado" if primeira_vez else "ja_registrado"}


@router.post("/api/v1/incidentes/{incidente_id}/decisao", response_model=DecisaoResponse,
             status_code=202, tags=["incidentes"])
def registrar_decisao(
    incidente_id: int, corpo: DecisaoRequest, conn=Depends(get_conn)
) -> DecisaoResponse:
    """Ponto em que o Human-in-the-Loop acontece.

    A decisão é persistida e a transação concluída **antes** de qualquer execução. Se o processo
    for interrompido no intervalo, o banco mostra aprovação sem execução: estado recuperável e
    auditável. A ordem inversa permitiria execução sem registro.
    """
    registro = queries.obter_incidente(conn, incidente_id)
    if registro is None:
        raise _erro(404, "incidente_inexistente", f"Incidente {incidente_id} não encontrado.")
    if registro["status_execucao"] != "pendente":
        raise _erro(
            409,
            "conflito_de_estado",
            f"Incidente {incidente_id} não está pendente de decisão.",
            status_atual=registro["status_execucao"],
        )

    if not decidir(conn, incidente_id, corpo.aprovado, corpo.operador, corpo.motivo):
        raise _erro(409, "conflito_de_estado",
                    f"A decisão sobre o incidente {incidente_id} já havia sido registrada.")

    if not corpo.aprovado:
        return DecisaoResponse(status="rejeitado", incidente_id=incidente_id)

    # Executor simulado até o marco v0.6.0: registra o que executaria, sem tocar em nada.
    try:
        executar(conn, incidente_id, ExecutorSimulado())
    except ExecucaoNaoAutorizadaError as exc:
        raise _erro(409, "execucao_nao_autorizada", str(exc)) from exc

    return DecisaoResponse(status="executando", incidente_id=incidente_id)


@router.get("/api/v1/incidentes/{incidente_id}/resultado", response_model=ResultadoResponse,
            tags=["incidentes"])
def resultado(incidente_id: int, conn=Depends(get_conn)) -> ResultadoResponse:
    registro = queries.obter_incidente(conn, incidente_id)
    if registro is None:
        raise _erro(404, "incidente_inexistente", f"Incidente {incidente_id} não encontrado.")
    mttr = registro["mttr_calculado"]
    return ResultadoResponse(
        incidente_id=incidente_id,
        status=registro["status_execucao"],
        exit_code=registro["exit_code"],
        output=registro["output_execucao"],
        erro=registro["output_erro"],
        ts_conclusao=registro["ts_conclusao"],
        mttr_segundos=mttr.total_seconds() if mttr else None,
    )


# ---------------------------------------------------------------------------
# Base de conhecimento e KPIs
# ---------------------------------------------------------------------------


@router.get("/api/v1/regras", tags=["base de conhecimento"])
def listar_regras(request: Request) -> dict[str, Any]:
    """Expõe a base carregada. Útil na defesa: mostra ao vivo que as regras são legíveis."""
    kb = request.app.state.kb
    return {
        "versao_kb": kb.versao_kb,
        "regras": [
            {
                "id": r.id,
                "nome": r.nome,
                "habilitada": r.habilitada,
                "tipo_alerta": r.condicao.tipo_alerta,
                "metrica": r.condicao.metrica,
                "limiar_uso_pct": r.condicao.limiar_uso_pct,
                "regex_log": r.condicao.regex_log,
                "diagnostico": r.diagnostico,
                "comando": r.render(r.remediacao.comando),
                "rollback": r.render(r.remediacao.rollback),
                "timeout_segundos": r.remediacao.timeout_segundos,
                "destrutiva": r.remediacao.destrutiva,
                "confianca_base": r.confianca_base,
            }
            for r in kb.regras
        ],
    }


@router.post("/api/v1/regras/reload", tags=["base de conhecimento"])
def recarregar_regras(request: Request) -> dict[str, Any]:
    """Recarrega a base sem reiniciar. Base inválida mantém a anterior ativa."""
    try:
        nova = carregar_kb()
    except KnowledgeBaseError as exc:
        raise _erro(422, "base_invalida", str(exc),
                    versao_ativa=request.app.state.kb.versao_kb) from exc
    request.app.state.kb = nova
    return {"status": "recarregada", "versao_kb": nova.versao_kb, "regras": len(nova.regras)}


@router.get("/api/v1/kpis", tags=["kpis"])
def kpis(conn=Depends(get_conn)) -> dict[str, Any]:
    return queries.kpis(conn)


# ---------------------------------------------------------------------------
# Saúde e simulação
# ---------------------------------------------------------------------------


@router.get("/health", response_model=Saude, tags=["saúde"])
def health(request: Request) -> Saude:
    kb = getattr(request.app.state, "kb", None)
    try:
        with conectar() as conexao:
            with conexao.cursor() as cur:
                cur.execute("SELECT 1")
        db = "ok"
    except Exception:
        db = "indisponivel"
    return Saude(
        status="ok" if db == "ok" and kb else "degradado",
        db=db,
        kb="ok" if kb else "nao carregada",
        versao=VERSAO_API,
        versao_kb=kb.versao_kb if kb else None,
        debug=request.app.state.settings.polaris_debug,
    )


@router.post("/debug/simulate-alert", response_model=IngestaoResponse, status_code=201,
             tags=["desenvolvimento"])
def simular_alerta(
    request: Request, corpo: AlertaSimulado, conn=Depends(get_conn)
) -> IngestaoResponse:
    """Injeta um alerta sem Zabbix.

    Destrava o desenvolvimento da interface antes da integração com a telemetria, e é o plano B
    caso a configuração do Zabbix atrase. Só existe com POLARIS_DEBUG habilitado.
    """
    if not request.app.state.settings.polaris_debug:
        raise _erro(404, "endpoint_indisponivel",
                    "Endpoints de simulação exigem POLARIS_DEBUG habilitado.")

    dados = corpo.model_dump()
    if not dados.get("id_evento"):
        dados["id_evento"] = f"sim-{queries.proximo_id_simulado(conn)}"

    ingestao = ingerir(conn, Alert.from_dict(dados), request.app.state.kb,
                       request.app.state.config)
    if ingestao.sem_regra:
        return IngestaoResponse(
            status="no_match",
            incidente_id=ingestao.incidente_id,
            motivo=f"nenhuma regra compatível com tipo_alerta={corpo.tipo_alerta}",
        )
    if ingestao.duplicado:
        return IngestaoResponse(status="duplicate", incidente_id=ingestao.incidente_id)

    s = ingestao.sugestao
    return IngestaoResponse(
        status="created",
        incidente_id=ingestao.incidente_id,
        regra=s.rule.id,
        confianca=s.confianca,
        banda=s.banda.value,
    )
