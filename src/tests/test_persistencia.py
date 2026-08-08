"""Testes de integração da camada de persistência.

Exigem um PostgreSQL de pé. Sem ele, são pulados em vez de falhar — o motor precisa continuar
testável em qualquer máquina, inclusive sem Docker.

    docker run --rm -d --name polaris-db-dev -e POSTGRES_PASSWORD=x \\
        -e POSTGRES_DB=polaris_audit -p 55432:5432 postgres:16
    DB_PORT=55432 DB_PASSWORD=x python -m src.db.migrate
    DB_PORT=55432 DB_PASSWORD=x pytest
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.db import queries
from src.engine.models import Banda
from src.engine.service import (
    ExecucaoNaoAutorizadaError,
    ExecutorSimulado,
    decidir,
    executar,
    exibir,
    ingerir,
)

AGORA = datetime.now(timezone.utc)


def test_ciclo_completo_grava_os_cinco_marcos(conn, kb, config, alerta):
    ing = ingerir(conn, alerta("service_down", id_evento="ev-ciclo"), kb, config,
                  usar_historico=False)
    assert ing.sugestao.rule.id == "R003"

    assert exibir(conn, ing.incidente_id) is True
    assert decidir(conn, ing.incidente_id, True, "tester") is True
    executar(conn, ing.incidente_id, ExecutorSimulado())

    reg = queries.obter_incidente(conn, ing.incidente_id)
    assert reg["status_execucao"] == "sucesso"
    assert reg["decisao_humana"] is True
    assert all(reg[c] is not None for c in
               ("ts_deteccao", "ts_criacao", "ts_exibicao", "ts_aprovacao", "ts_conclusao"))
    assert reg["mttr_calculado"] is not None
    assert reg["ts_criacao"] <= reg["ts_exibicao"] <= reg["ts_aprovacao"] <= reg["ts_conclusao"]


def test_execucao_sem_aprovacao_e_recusada(conn, kb, config, alerta):
    """A invariante central do trabalho, verificada e não apenas prometida."""
    ing = ingerir(conn, alerta("disk_full", id_evento="ev-sem-aprovacao"), kb, config,
                  usar_historico=False)
    with pytest.raises(ExecucaoNaoAutorizadaError, match="aprovação humana"):
        executar(conn, ing.incidente_id, ExecutorSimulado())
    assert queries.obter_incidente(conn, ing.incidente_id)["status_execucao"] == "pendente"


def test_execucao_apos_rejeicao_e_recusada(conn, kb, config, alerta):
    ing = ingerir(conn, alerta("disk_full", id_evento="ev-rejeitado"), kb, config,
                  usar_historico=False)
    decidir(conn, ing.incidente_id, False, "tester", motivo="janela de manutenção")
    with pytest.raises(ExecucaoNaoAutorizadaError):
        executar(conn, ing.incidente_id, ExecutorSimulado())
    reg = queries.obter_incidente(conn, ing.incidente_id)
    assert reg["status_execucao"] == "rejeitado"
    assert reg["motivo_rejeicao"] == "janela de manutenção"
    assert reg["ts_conclusao"] is None


def test_decisao_em_incidente_ja_decidido_e_recusada(conn, kb, config, alerta):
    ing = ingerir(conn, alerta("disk_full", id_evento="ev-dupla-decisao"), kb, config,
                  usar_historico=False)
    assert decidir(conn, ing.incidente_id, True, "tester") is True
    assert decidir(conn, ing.incidente_id, False, "outro") is False


def test_evento_reentregue_nao_duplica(conn, kb, config, alerta):
    a = alerta("service_down", id_evento="ev-duplicado")
    primeira = ingerir(conn, a, kb, config, usar_historico=False)
    segunda = ingerir(conn, a, kb, config, usar_historico=False)
    assert segunda.duplicado is True
    assert segunda.incidente_id == primeira.incidente_id


def test_exibicao_nao_reinicia_a_contagem(conn, kb, config, alerta):
    """Reabrir a tela não pode zerar t3, senão o tempo de decisão humana fica subestimado."""
    ing = ingerir(conn, alerta("disk_full", id_evento="ev-exibicao"), kb, config,
                  usar_historico=False)
    assert exibir(conn, ing.incidente_id) is True
    primeiro = queries.obter_incidente(conn, ing.incidente_id)["ts_exibicao"]
    assert exibir(conn, ing.incidente_id) is False
    assert queries.obter_incidente(conn, ing.incidente_id)["ts_exibicao"] == primeiro


def test_alerta_sem_regra_e_registrado_como_no_match(conn, kb, config, alerta):
    """Reconhecer que não sabe é resultado da pesquisa, não falha a ser escondida."""
    ing = ingerir(conn, alerta("sem_regra", id_evento="ev-no-match"), kb, config,
                  usar_historico=False)
    assert ing.sem_regra is True
    assert ing.sugestao is None
    assert queries.obter_incidente(conn, ing.incidente_id)["status_execucao"] == "no_match"


def test_falha_de_execucao_nao_fecha_o_incidente(conn, kb, config, alerta):
    """Sem confirmação de saúde não há t5: código de retorno não é prova de restabelecimento."""
    ing = ingerir(conn, alerta("service_down", id_evento="ev-falha"), kb, config,
                  usar_historico=False)
    decidir(conn, ing.incidente_id, True, "tester")
    executar(conn, ing.incidente_id, ExecutorSimulado(saudavel=False))
    reg = queries.obter_incidente(conn, ing.incidente_id)
    assert reg["status_execucao"] == "falha"
    assert reg["ts_conclusao"] is None


def test_trace_persiste_como_jsonb_consultavel(conn, kb, config, alerta):
    ing = ingerir(conn, alerta("disk_full", id_evento="ev-trace"), kb, config,
                  usar_historico=False)
    reg = queries.obter_incidente(conn, ing.incidente_id)
    trace = reg["explicabilidade"]
    assert trace["regra"] == "R001"
    assert len(trace["fatores"]) == 5
    with conn.cursor() as cur:
        cur.execute(
            "SELECT explicabilidade->>'banda' AS banda FROM audit_log WHERE id = %s",
            (ing.incidente_id,),
        )
        assert cur.fetchone()["banda"] == "alta"


def test_historico_ignora_rejeitados_e_pendentes(conn, kb, config, alerta):
    for i in range(3):
        ing = ingerir(conn, alerta("cpu_high", id_evento=f"ev-hist-ok-{i}"), kb, config,
                      usar_historico=False)
        decidir(conn, ing.incidente_id, True, "tester")
        executar(conn, ing.incidente_id, ExecutorSimulado())
    rejeitado = ingerir(conn, alerta("cpu_high", id_evento="ev-hist-rej"), kb, config,
                        usar_historico=False)
    decidir(conn, rejeitado.incidente_id, False, "tester")
    ingerir(conn, alerta("cpu_high", id_evento="ev-hist-pend"), kb, config, usar_historico=False)

    hist = queries.historico_regra(conn, "R002")
    assert hist.n == 3
    assert hist.sucessos == 3


def test_recorrencia_conta_apenas_sucessos_no_mesmo_host(conn, kb, config, alerta):
    for i in range(2):
        ing = ingerir(conn, alerta("service_down", id_evento=f"ev-rec-{i}"), kb, config,
                      usar_historico=False)
        decidir(conn, ing.incidente_id, True, "tester")
        executar(conn, ing.incidente_id, ExecutorSimulado())

    assert queries.recorrencia(conn, "vm-alvo-01", "R003").k == 2
    assert queries.recorrencia(conn, "outro-host", "R003").k == 0
    assert queries.recorrencia(conn, "vm-alvo-01", "R001").k == 0


def test_recorrencia_derruba_a_confianca_para_banda_baixa(conn, kb, config, alerta):
    """O caminho completo do fator F4: banco -> histórico -> confiança -> banda."""
    for i in range(2):
        ing = ingerir(conn, alerta("service_down", id_evento=f"ev-flap-{i}"), kb, config,
                      usar_historico=False)
        decidir(conn, ing.incidente_id, True, "tester")
        executar(conn, ing.incidente_id, ExecutorSimulado())

    terceira = ingerir(conn, alerta("service_down", id_evento="ev-flap-3"), kb, config,
                       usar_historico=True)
    assert terceira.sugestao.banda is Banda.BAIXA
    f4 = next(f for f in terceira.sugestao.trace.fatores if f.id == "F4")
    assert f4.valor == pytest.approx(0.60)
    assert "flapping" in f4.motivo


def test_rodada_de_experimento_calcula_mttr(conn):
    inicio = AGORA
    rodada_id = queries.criar_rodada(conn, "disk_full", "baseline", 1, inicio,
                                     versao_sistema="v0.3.0", operador="tester")
    queries.concluir_rodada(conn, rodada_id, inicio + timedelta(seconds=312),
                            passos_manuais=9, resolvido=True)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT mttr, passos_manuais FROM experiment_run WHERE id = %s", (rodada_id,))
        linha = cur.fetchone()
    assert linha["mttr"] == timedelta(seconds=312)
    assert linha["passos_manuais"] == 9


def test_rodada_descartada_nao_entra_nos_kpis(conn):
    inicio = AGORA
    descartada = queries.criar_rodada(conn, "cpu_high", "baseline", 99, inicio)
    queries.concluir_rodada(conn, descartada, inicio + timedelta(seconds=999), passos_manuais=50)
    queries.descartar_rodada(conn, descartada, "ensaio geral, dado não aproveitável")
    conn.commit()

    resultado = queries.kpis(conn)
    passos = [r for r in resultado["kpi02_passos"] if r["cenario"] == "cpu_high"]
    assert all(r["passos_max"] != 50 for r in passos)


def test_views_de_kpi_respondem(conn):
    resultado = queries.kpis(conn)
    assert set(resultado) == {"kpi01_mttr", "kpi02_passos", "kpi03_acerto", "decomposicao_mttr"}
