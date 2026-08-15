"""Acesso ao banco de auditoria.

Funções puras de SQL: recebem a conexão, não abrem transação por conta própria e não decidem nada.
A ordem das operações — em especial gravar a decisão humana **antes** de qualquer execução — é
responsabilidade de `engine/service.py`, onde a invariante do trabalho é imposta.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from psycopg.types.json import Jsonb

from ..engine.history import Historico, HistoricoRegra, Recorrencia
from ..engine.models import Alert, Suggestion

ESTADOS_ABERTOS = ("pendente", "executando")
ESTADOS_CONCLUIDOS = ("sucesso", "falha", "timeout")


@dataclass(frozen=True, slots=True)
class Ingestao:
    incidente_id: int
    duplicado: bool = False
    sem_regra: bool = False


# ---------------------------------------------------------------------------
# Ciclo de vida do incidente
# ---------------------------------------------------------------------------


def incidente_aberto_por_evento(conn, id_evento: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM audit_log WHERE id_evento = %s AND status_execucao = ANY(%s)",
            (id_evento, list(ESTADOS_ABERTOS)),
        )
        linha = cur.fetchone()
    return linha["id"] if linha else None


def criar_incidente(
    conn,
    alert: Alert,
    sugestao: Suggestion | None,
    experiment_run_id: int | None = None,
) -> Ingestao:
    """Persiste o incidente já analisado. Não executa nada: `status_execucao` nasce 'pendente'.

    Reentrega do mesmo evento pelo webhook devolve o incidente existente em vez de duplicar.
    """
    if alert.id_evento:
        existente = incidente_aberto_por_evento(conn, alert.id_evento)
        if existente is not None:
            return Ingestao(incidente_id=existente, duplicado=True)

    if sugestao is None:
        # Ausência de regra compatível é resultado, não falha: o sistema reconhece que não sabe.
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (id_evento, hostname, severidade, status_execucao,
                                       ts_deteccao, experiment_run_id)
                VALUES (%s, %s, %s, 'no_match', %s, %s)
                RETURNING id
                """,
                (alert.id_evento, alert.hostname, alert.severidade,
                 alert.ts_deteccao, experiment_run_id),
            )
            return Ingestao(incidente_id=cur.fetchone()["id"], sem_regra=True)

    trace = sugestao.trace
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (id_evento, hostname, severidade,
                                   regra_disparada, confianca_calculada, banda_confianca,
                                   explicabilidade, versao_kb, versao_motor,
                                   comando_executado, comando_verificacao, status_execucao,
                                   ts_deteccao, experiment_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pendente', %s, %s)
            RETURNING id
            """,
            (alert.id_evento, alert.hostname, alert.severidade,
             sugestao.rule.id, trace.confianca_final, trace.banda.value,
             Jsonb(trace.to_dict()), trace.versao_kb, trace.versao_motor,
             sugestao.comando, sugestao.verificador, alert.ts_deteccao, experiment_run_id),
        )
        return Ingestao(incidente_id=cur.fetchone()["id"])


def marcar_exibicao(conn, incidente_id: int) -> bool:
    """Registra t3. Só grava na primeira vez: reabrir a tela não pode reiniciar a contagem do
    tempo de decisão, senão o KPI de decisão humana fica subestimado."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE audit_log SET ts_exibicao = NOW() "
            "WHERE id = %s AND ts_exibicao IS NULL RETURNING id",
            (incidente_id,),
        )
        return cur.fetchone() is not None


def registrar_decisao(
    conn, incidente_id: int, aprovado: bool, operador: str, motivo: str | None = None
) -> bool:
    """Registra t4. Retorna False se o incidente não estava pendente.

    Esta é a gravação que autoriza a execução. Quem chama precisa concluir a transação **antes**
    de disparar qualquer comando — ver `engine/service.py`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit_log
               SET decisao_humana = %s,
                   operador = %s,
                   motivo_rejeicao = %s,
                   ts_aprovacao = NOW(),
                   status_execucao = CASE WHEN %s THEN 'executando' ELSE 'rejeitado' END
             WHERE id = %s AND status_execucao = 'pendente'
            RETURNING id
            """,
            (aprovado, operador, motivo, aprovado, incidente_id),
        )
        return cur.fetchone() is not None


def registrar_execucao(
    conn,
    incidente_id: int,
    status: str,
    exit_code: int | None = None,
    saida: str | None = None,
    erro: str | None = None,
    concluir: bool = True,
) -> None:
    """Registra o resultado. `ts_conclusao` (t5) só é gravado quando o verificador confirmou saúde.

    O código de retorno do comando não fecha o incidente: um reinício de serviço pode retornar 0 e
    o serviço cair em seguida. Daí `concluir` ser parâmetro separado de `status`.
    """
    if status not in ESTADOS_CONCLUIDOS:
        raise ValueError(f"status de execução inválido: {status}")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE audit_log
               SET status_execucao = %s,
                   exit_code = %s,
                   output_execucao = %s,
                   output_erro = %s,
                   ts_conclusao = CASE WHEN %s THEN NOW() ELSE ts_conclusao END
             WHERE id = %s
            """,
            (status, exit_code, saida, erro, concluir, incidente_id),
        )


def obter_incidente(conn, incidente_id: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM audit_log WHERE id = %s", (incidente_id,))
        return cur.fetchone()


def listar_incidentes(conn, status: str | None = "pendente", limite: int = 50) -> list[dict]:
    with conn.cursor() as cur:
        if status:
            cur.execute(
                """
                SELECT id, id_evento, hostname, severidade, regra_disparada,
                       confianca_calculada, banda_confianca, status_execucao, ts_criacao
                  FROM audit_log WHERE status_execucao = %s
                 ORDER BY ts_criacao DESC LIMIT %s
                """,
                (status, limite),
            )
        else:
            cur.execute(
                """
                SELECT id, id_evento, hostname, severidade, regra_disparada,
                       confianca_calculada, banda_confianca, status_execucao, ts_criacao
                  FROM audit_log ORDER BY ts_criacao DESC LIMIT %s
                """,
                (limite,),
            )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Histórico para os fatores F3 e F4 do modelo de confiança
# ---------------------------------------------------------------------------


def historico_regra(conn, regra: str, janela_dias: int = 90) -> HistoricoRegra:
    """Execuções aprovadas e já concluídas desta regra na janela. Alimenta o fator F3.

    Incidentes rejeitados ficam de fora: eles medem a decisão do operador, não o desempenho da
    heurística. Incidentes ainda pendentes também, por não terem desfecho.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE status_execucao = 'sucesso') AS sucessos
              FROM audit_log
             WHERE regra_disparada = %s
               AND decisao_humana IS TRUE
               AND status_execucao = ANY(%s)
               AND ts_criacao >= NOW() - make_interval(days => %s)
            """,
            (regra, list(ESTADOS_CONCLUIDOS), janela_dias),
        )
        linha = cur.fetchone()
    return HistoricoRegra(n=linha["n"], sucessos=linha["sucessos"])


def recorrencia(conn, hostname: str, regra: str, janela_minutos: int = 30) -> Recorrencia:
    """Quantas vezes esta combinação host+regra já foi remediada com sucesso na janela. Fator F4.

    Só conta remediação **bem-sucedida**: se a anterior falhou, o problema persistir é esperado e
    não caracteriza que a correção "não sustentou".
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS k
              FROM audit_log
             WHERE hostname = %s
               AND regra_disparada = %s
               AND decisao_humana IS TRUE
               AND status_execucao = 'sucesso'
               AND ts_conclusao >= NOW() - make_interval(mins => %s)
            """,
            (hostname, regra, janela_minutos),
        )
        return Recorrencia(k=cur.fetchone()["k"])


def carregar_historico(conn, hostname: str, regra: str, config: dict) -> Historico:
    """Resolve as estatísticas de auditoria que o cálculo de confiança consome.

    O cálculo em si nunca toca o banco: recebe estes valores prontos, o que mantém a fórmula
    testável com dados fabricados e o motor utilizável sem infraestrutura.
    """
    return Historico(
        regra=historico_regra(conn, regra, config["F3"]["janela_dias"]),
        recorrencia=recorrencia(conn, hostname, regra, config["F4"]["janela_minutos"]),
    )


# ---------------------------------------------------------------------------
# Instrumentação do experimento
# ---------------------------------------------------------------------------


def criar_rodada(
    conn,
    cenario: str,
    braco: str,
    rodada: int,
    ts_injecao: datetime,
    versao_sistema: str | None = None,
    commit_sha: str | None = None,
    versao_kb: str | None = None,
    host_alvo: str | None = None,
    operador: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO experiment_run (cenario, braco, rodada, ts_injecao, versao_sistema,
                                        commit_sha, versao_kb, host_alvo, operador)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (cenario, braco, rodada, ts_injecao, versao_sistema,
             commit_sha, versao_kb, host_alvo, operador),
        )
        return cur.fetchone()["id"]


def concluir_rodada(
    conn,
    rodada_id: int,
    ts_verificado_ok: datetime,
    passos_manuais: int | None = None,
    comandos_usados: str | None = None,
    resolvido: bool | None = None,
    observacoes: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE experiment_run
               SET ts_verificado_ok = %s, passos_manuais = %s, comandos_usados = %s,
                   resolvido = %s, observacoes = %s
             WHERE id = %s
            """,
            (ts_verificado_ok, passos_manuais, comandos_usados, resolvido,
             observacoes, rodada_id),
        )


def descartar_rodada(conn, rodada_id: int, motivo: str) -> None:
    """Dado primário não se apaga: marca-se como descartado e registra-se o porquê."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE experiment_run SET descartada = TRUE, motivo_descarte = %s WHERE id = %s",
            (motivo, rodada_id),
        )


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------


def kpis(conn) -> dict[str, list[dict]]:
    resultado: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        for chave, view in (
            ("kpi01_mttr", "vw_kpi01_mttr"),
            ("kpi02_passos", "vw_kpi02_passos"),
            ("kpi03_acerto", "vw_kpi03_acerto"),
            ("decomposicao_mttr", "vw_decomposicao_mttr"),
        ):
            cur.execute(f"SELECT * FROM {view}")
            resultado[chave] = cur.fetchall()
    return resultado


def proximo_id_simulado(conn) -> int:
    """Sequência simples para dar identificador único a alertas simulados no modo de depuração."""
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 AS proximo FROM audit_log")
        return cur.fetchone()["proximo"]


def incidentes_abertos(conn) -> list[dict]:
    """Incidentes ainda aguardando decisão ou execução. Usado pela reconciliação."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, id_evento, hostname, regra_disparada FROM audit_log "
            "WHERE status_execucao = ANY(%s) ORDER BY ts_criacao",
            (list(ESTADOS_ABERTOS),),
        )
        return cur.fetchall()


def encerrar_por_origem(conn, incidente_id: int) -> None:
    """Fecha um incidente cujo problema já não existe no Zabbix.

    Distingue-se de uma remediação bem-sucedida: não houve decisão humana nem execução, então o
    registro não pode contar como acerto de heurística no KPI 03.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE audit_log SET status_execucao = 'encerrado_na_origem', ts_conclusao = NOW() "
            "WHERE id = %s AND status_execucao = ANY(%s)",
            (incidente_id, list(ESTADOS_ABERTOS)),
        )
