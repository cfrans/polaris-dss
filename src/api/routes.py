"""Endpoints da API.

As rotas orquestram e traduzem; a decisão de negócio fica em `engine/service.py`. Em especial, é o
serviço — e não esta camada — que impõe a exigência de aprovação humana antes de qualquer execução.

Os manipuladores são funções síncronas de propósito: o driver do PostgreSQL é síncrono, e o FastAPI
executa rotas `def` numa pool de threads. Declará-las `async def` bloquearia o laço de eventos.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from ..db import queries
from ..db.connection import conectar
from ..engine.diagnostico import executar as executar_diagnostico
from ..engine.diagnostico import check_connections
from ..engine.server_metrics import get_server_metrics
from ..engine.knowledge_base import KnowledgeBaseError
from ..engine.knowledge_base import load as carregar_kb
from ..engine.models import Alert
from ..engine.script_catalog import load_catalog
from ..engine.zabbix_client import (
    ZabbixClient,
    ZabbixError,
    enriquecer_timestamp,
    normalizar_webhook,
)
from ..engine.service import (
    ExecucaoNaoAutorizadaError,
    decidir,
    executar,
    executor_padrao,
    exibir,
    ingerir,
)
from .schemas import (
    AlertaSimulado,
    EventoZabbix,
    EstadoReconciliacao,
    CicloReconciliacao,
    DecisaoRequest,
    DecisaoResponse,
    IncidenteDetalhe,
    IncidenteResumo,
    IngestaoResponse,
    HistoricoOcorrencias,
    OcorrenciaHistorica,
    ListaIncidentes,
    ResultadoResponse,
    Saude,
    PreferencesRequest,
)

router = APIRouter()
VERSAO_API = "1.1.0-dev"
LOGGER = logging.getLogger(__name__)


@router.get("/api/v1/scripts-padrao", tags=["remediação"])
def list_default_scripts() -> dict[str, Any]:
    """Expõe os mesmos bytes padrão que o executor enviará pela sessão SSH."""
    catalog = load_catalog()
    return {
        "versao": catalog.sha256,
        "scripts": [
            {"nome": script.name, "sha256": script.sha256,
             "conteudo": script.content.decode("utf-8")}
            for script in catalog.scripts
        ],
    }


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

    Analisa, persiste como pendente e coleta evidências de leitura. A remediação depende
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

    if alerta.ts_deteccao is None and alerta.id_evento:
        settings = request.app.state.settings
        if settings.zabbix_url:
            cliente_zabbix = ZabbixClient(
                url=settings.zabbix_url,
                usuario=settings.zabbix_user,
                senha=settings.zabbix_password,
                token=settings.zabbix_token,
            )
            try:
                alerta = enriquecer_timestamp(alerta, cliente_zabbix)
            except ZabbixError as exc:
                LOGGER.warning("não foi possível obter o timestamp do evento %s: %s",
                               alerta.id_evento, exc)

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
    include_unmatched: bool = Query(default=True),
    conn=Depends(get_conn),
) -> ListaIncidentes:
    kb = request.app.state.kb
    linhas = queries.listar_incidentes(conn, status=status or None, limite=limit,
                                      include_unmatched=include_unmatched)
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


@router.get("/api/v1/historico-decisoes", tags=["incidentes"])
def decision_history(
    period: Literal["24h", "7d", "30d"] = Query(default="7d"), conn=Depends(get_conn),
) -> dict[str, Any]:
    """Read operational human decisions, independently of experimental KPI eligibility."""
    return queries.read_decision_history(conn, period)


@router.get("/api/v1/incidentes/{incidente_id}/ocorrencias",
            response_model=HistoricoOcorrencias, tags=["incidentes"])
def occurrence_history(incidente_id: int, conn=Depends(get_conn)) -> HistoricoOcorrencias:
    incident = queries.obter_incidente(conn, incidente_id)
    if incident is None:
        raise _erro(404, "incidente_inexistente", f"Incidente {incidente_id} não encontrado.")
    preferences = queries.read_preferences(conn)
    days = preferences["periodo_ocorrencias_dias"]
    rule_id = incident["regra_disparada"]
    rows = queries.incident_history(conn, incident["hostname"], rule_id, days)
    items = [OcorrenciaHistorica(
        id=row["id"], id_evento=row["id_evento"], status=row["status_execucao"],
        ts_deteccao=row["ts_deteccao"], ts_criacao=row["ts_criacao"],
        ts_conclusao=row["ts_conclusao"],
    ) for row in rows]
    return HistoricoOcorrencias(
        hostname=incident["hostname"] or "", regra=rule_id or "", periodo_dias=days,
        total=rows[0]["total"] if rows else 0,
        itens=items,
    )


@router.get("/api/v1/incidentes/{incidente_id}", response_model=IncidenteDetalhe,
            tags=["incidentes"])
def detalhar(request: Request, incidente_id: int, conn=Depends(get_conn)) -> IncidenteDetalhe:
    registro = queries.obter_incidente(conn, incidente_id)
    if registro is None:
        raise _erro(404, "incidente_inexistente", f"Incidente {incidente_id} não encontrado.")

    kb = request.app.state.kb
    period_days = queries.read_preferences(conn)["periodo_ocorrencias_dias"]
    regra = kb.por_id(registro["regra_disparada"] or "")
    trace = registro["explicabilidade"] or {}
    zabbix_host_url = None
    settings = request.app.state.settings
    if settings.zabbix_url and registro["id_evento"]:
        client = ZabbixClient(url=settings.zabbix_url, usuario=settings.zabbix_user,
                              senha=settings.zabbix_password, token=settings.zabbix_token)
        try:
            zabbix_host_url = client.url_host_do_evento(registro["id_evento"])
        except ZabbixError as exc:
            LOGGER.info("link do host no Zabbix indisponível para incidente %s: %s",
                        incidente_id, exc)

    return IncidenteDetalhe(
        id=registro["id"],
        id_evento=registro["id_evento"],
        hostname=registro["hostname"],
        ip_address=str(registro["ip_address"]) if registro["ip_address"] is not None else None,
        zabbix_host_url=zabbix_host_url,
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
        plano=trace.get("plano"),
        acao_escolhida=trace.get("acao_escolhida"),
        confianca_base=trace.get("confianca_base"),
        versao_kb=registro["versao_kb"],
        versao_motor=registro["versao_motor"],
        versao_scripts=registro["versao_scripts"],
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
        ocorrencias_periodo=queries.incident_occurrences(
            conn, registro["hostname"], registro["regra_disparada"], period_days),
        periodo_ocorrencias_dias=period_days,
    )


@router.patch("/api/v1/incidentes/{incidente_id}/exibicao", tags=["incidentes"])
def marcar_exibicao(incidente_id: int, conn=Depends(get_conn)) -> dict[str, Any]:
    """Registra o instante em que a interface apresentou o incidente ao operador.

    Sem este marco não existe tempo de decisão humana, e sem ele o MTTR não pode ser decomposto —
    que é a análise mais informativa do experimento. A interface é obrigada a chamar este endpoint.
    """
    incident = queries.obter_incidente(conn, incidente_id)
    if incident is None:
        raise _erro(404, "incidente_inexistente", f"Incidente {incidente_id} não encontrado.")
    if ((incident["explicabilidade"] or {}).get("plano") or {}).get("estado") == "coletando":
        raise _erro(409, "diagnostico_em_andamento", "Aguarde o diagnóstico antes de registrar a apresentação.")
    primeira_vez = exibir(conn, incidente_id)
    return {"status": "registrado" if primeira_vez else "ja_registrado"}


@router.post("/api/v1/incidentes/{incidente_id}/decisao", response_model=DecisaoResponse,
             status_code=202, tags=["incidentes"])
def registrar_decisao(
    request: Request, incidente_id: int, corpo: DecisaoRequest, conn=Depends(get_conn)
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

    catalog = None
    action = None
    if corpo.aprovado:
        catalog = load_catalog()
        if corpo.versao_scripts != catalog.sha256:
            raise _erro(409, "scripts_alterados",
                        "Os scripts padrão mudaram. Revise o conteúdo antes de aprovar.")
        regra_atual = request.app.state.kb.por_id(registro["regra_disparada"] or "")
        if (regra_atual is None
                or registro["comando_executado"] != regra_atual.render(regra_atual.remediacao.comando)
                or registro["comando_verificacao"] != regra_atual.render(regra_atual.remediacao.verificador)):
            raise _erro(409, "regra_alterada",
                        "A regra ou o comando mudou. Gere um novo incidente antes de aprovar.")

        from dataclasses import asdict
        from ..engine.action_plans import PLAN_RULES, choose_action, digest
        plan = (registro["explicabilidade"] or {}).get("plano")
        if plan:
            preferences = queries.read_preferences(conn, lock=True)
            if (plan.get("regra_sha256") != digest(asdict(regra_atual))
                    or (plan.get("versao_scripts") and plan["versao_scripts"] != catalog.sha256)
                    or plan.get("preferencias", {}).get("versao") != preferences["versao"]
                    or plan.get("historico_habilitado") != request.app.state.settings.polaris_confidence_history):
                raise _erro(409, "plano_alterado", "Regra ou preferências mudaram. Atualize o diagnóstico.")
            try:
                action = choose_action(plan, corpo.versao_plano, corpo.opcao_id)
            except ValueError as exc:
                raise _erro(409, "plano_invalido", str(exc)) from exc
        elif (request.app.state.settings.target_ssh_host and registro["regra_disparada"] in PLAN_RULES):
            raise _erro(409, "diagnostico_necessario", "Atualize o diagnóstico antes da remediação real.")

    decision_args = {"versao_scripts": catalog.sha256 if catalog else None}
    if action is not None:
        decision_args.update(action=action, plan_version=corpo.versao_plano)
    from . import auth
    user = request.state.user
    auth.authorize_decision(conn, user)
    if corpo.aprovado and not auth.acknowledged(user, catalog.sha256):
        raise _erro(409, 'ciencia_necessaria', 'Revise e confirme a ciência dos scripts antes de aprovar.')
    if not decidir(conn, incidente_id, corpo.aprovado, user['login'], corpo.motivo, **decision_args):
        raise _erro(409, "conflito_de_estado",
                    f"A decisão sobre o incidente {incidente_id} já havia sido registrada.")

    if not corpo.aprovado:
        return DecisaoResponse(status="rejeitado", incidente_id=incidente_id)

    # Sem TARGET_SSH_HOST configurado, `executor_padrao` devolve o executor simulado e nada é
    # executado no host alvo.
    regra = request.app.state.kb.por_id(registro["regra_disparada"] or "")
    timeout = regra.remediacao.timeout_segundos if regra else 60
    try:
        executar(conn, incidente_id, executor_padrao(catalog), timeout_segundos=timeout)
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


@router.get("/api/v1/diagnostico", tags=["diagnóstico"])
def diagnostico(request: Request) -> dict[str, Any]:
    """Verifica banco, esquema, base de conhecimento, API do Zabbix e host alvo.

    É a primeira tela a abrir quando algo não funciona: em vez de descobrir por tentativa qual
    dependência caiu, cada uma responde por si com estado e latência. Segredos aparecem mascarados.
    """
    return executar_diagnostico(getattr(request.app.state, "kb", None)).to_dict()


@router.get("/api/v1/conectividade", tags=["diagnóstico"])
def connectivity() -> dict[str, Any]:
    """Read-only API/database probes for the header, without SSH or configuration values."""
    return check_connections()


@router.get("/api/v1/servidor", tags=["diagnóstico"])
def server_metrics() -> dict[str, Any]:
    """Read recent CPU and memory samples from the explicitly configured Zabbix host."""
    return get_server_metrics()


@router.get("/api/v1/kpis", tags=["kpis"])
def kpis(conn=Depends(get_conn)) -> dict[str, Any]:
    return queries.kpis(conn)


def _ciclo_reconciliacao(linha: dict) -> CicloReconciliacao:
    return CicloReconciliacao(
        status=linha["status"],
        recuperados=linha["recuperados"],
        ja_conhecidos=linha["ja_conhecidos"],
        encerrados_na_origem=linha["encerrados_na_origem"],
        mensagem_erro=linha["mensagem_erro"],
        ts_inicio=linha["ts_inicio"],
        ts_conclusao=linha["ts_conclusao"],
    )


@router.get("/api/v1/reconciliacao", response_model=EstadoReconciliacao,
            tags=["reconciliação"])
def estado_reconciliacao(request: Request, conn=Depends(get_conn)) -> EstadoReconciliacao:
    """Expõe configuração, último ciclo, atividade significativa e contagens sem alterar estado."""
    intervalo = request.app.state.settings.polaris_polling_segundos
    estado = queries.estado_reconciliacao(conn)

    if intervalo <= 0:
        status = "desativada"
    elif estado is None:
        status = "aguardando_primeiro_ciclo"
    elif estado["status"] == "erro":
        status = "erro"
    else:
        tolerancia = timedelta(seconds=max(intervalo * 3, 60))
        atrasada = datetime.now(timezone.utc) - estado["ts_conclusao"] > tolerancia
        status = "atrasada" if atrasada else "sucesso"

    return EstadoReconciliacao(
        habilitada=intervalo > 0,
        operacional=status == "sucesso",
        status=status,
        intervalo_segundos=intervalo,
        ultimo_ciclo=_ciclo_reconciliacao(estado) if estado else None,
        contagens_incidentes=queries.contagens_incidentes_por_status(conn),
        historico=[_ciclo_reconciliacao(linha)
                   for linha in queries.historico_reconciliacao(conn)],
    )


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

@router.get("/api/v1/preferencias", tags=["preferências"])
def preferences(request: Request, conn=Depends(get_conn)):
    return {**queries.read_preferences(conn),
            "historico_habilitado": request.app.state.settings.polaris_confidence_history}


@router.put("/api/v1/preferencias", tags=["preferências"])
def update_preferences(request: Request, body: PreferencesRequest, conn=Depends(get_conn)):
    saved = queries.save_preferences(conn, body.modo_preferencia, body.desconto_maximo,
                                    body.minimo_escolhas, body.periodo_ocorrencias_dias)
    return {**saved, "historico_habilitado": request.app.state.settings.polaris_confidence_history}


@router.post("/api/v1/incidentes/{incidente_id}/diagnostico", tags=["diagnóstico"])
def refresh_diagnostic(request: Request, incidente_id: int, conn=Depends(get_conn)):
    from dataclasses import replace
    from ..engine.action_plans import build_plan, collect_evidence
    from ..engine.engine import analisar
    from ..engine.models import Banda, Fator
    row = queries.obter_incidente(conn, incidente_id)
    if row is None or row["status_execucao"] != "pendente":
        raise _erro(409, "conflito_de_estado", "Somente um incidente pendente pode ter diagnóstico atualizado.")
    rule = request.app.state.kb.por_id(row["regra_disparada"] or "")
    if rule is None:
        raise _erro(409, "regra_inexistente", "Não há regra carregada para este incidente.")
    trace = row["explicabilidade"] or {}
    evidence = trace.get("evidencias", {})
    metric = evidence.get("metrica", {})
    alert = Alert(tipo_alerta=rule.condicao.tipo_alerta, hostname=row["hostname"],
                  ip_address=str(row["ip_address"]) if row["ip_address"] else None,
                  texto=evidence.get("texto", {}).get("trecho") or "",
                  valor=metric.get("valor"), metrica=metric.get("chave"), severidade=row["severidade"])
    suggestion = analisar(alert, request.app.state.kb, request.app.state.config)
    if suggestion is None or suggestion.rule.id != rule.id:
        raise _erro(409, "regra_alterada", "O evento não corresponde mais à regra vigente.")
    # Atualizar metadados remotos não reescreve a confiança técnica histórica do evento.
    suggestion = replace(suggestion, trace=replace(suggestion.trace,
                          confianca_final=trace["confianca_final"], banda=Banda(trace["banda"]),
                          fatores=tuple(Fator(**factor) for factor in trace["fatores"])))
    remote = collect_evidence(alert)
    if remote is None:
        raise _erro(409, "alvo_indisponivel", "Alvo de diagnóstico não configurado.")
    history = request.app.state.settings.polaris_confidence_history
    pref = queries.read_preferences(conn)
    choices = queries.action_choices(conn, alert.hostname, rule.id) if history else {}
    outcomes = queries.action_outcomes(conn, alert.hostname, rule.id) if history else {}
    plan = build_plan(suggestion, remote, pref, choices, history, request.app.state.config, outcomes)
    if not queries.update_plan(conn, incidente_id, plan, trace.get("plano", {}).get("versao")):
        raise _erro(409, "conflito_de_estado", "O incidente recebeu uma decisão durante a inspeção.")
    return plan
