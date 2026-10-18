"""Plans must survive either ingestion path and concurrent duplicate delivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace

import pytest

from src.db import queries
from src.db.connection import conectar
from src.engine import action_plans
from src.engine.config import get_settings
from src.engine.reconciliacao import reconciliar
from src.engine.service import ingerir


def diagnostic(scenario):
    common = {"tipo": scenario, "coletado_em": datetime.now(timezone.utc).isoformat(),
              "completo": True}
    if scenario == "service_down":
        return dict(common, estado_servico="inactive", indicios=[])
    if scenario == "cpu_high":
        return dict(common, processo={"pid": 555, "nome": "stress-ng-cpu", "cpu_pct": 99,
                                     "inicio": "fixture"})
    return dict(common, espaco_livre=1000000, arquivos=[{
        "caminho": "/mnt/polaris_test/old.log.gz", "bytes": 100, "mtime_ns": 1,
        "ctime_ns": 2, "inode": 3, "dispositivo": 4, "uid": 0, "modo": 0o600,
        "links": 1, "idade_s": 8 * 86400, "aberto": False, "proprietario": "root"}])


@pytest.fixture
def configured_inspection(monkeypatch):
    monkeypatch.setenv("TARGET_SSH_HOST", "192.0.2.152")
    monkeypatch.setenv("POLARIS_CONFIDENCE_HISTORY", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(action_plans, "collect_evidence", lambda alert: diagnostic(alert.tipo_alerta))
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("scenario", ["disk_full", "cpu_high", "service_down"])
@pytest.mark.parametrize("first", ["polling", "webhook"])
def test_both_ingestion_orders_persist_one_actionable_plan_without_approval(
        conn, kb, config, alerta, configured_inspection, scenario, first):
    alert = alerta(scenario, id_evento="ingestion-plan", ip_address="192.0.2.152")
    client = SimpleNamespace(alertas_abertos=lambda: [alert])
    if first == "polling":
        assert reconciliar(conn, client, kb, config).recuperados == 1
        assert ingerir(conn, alert, kb, config).duplicado
    else:
        assert not ingerir(conn, alert, kb, config).duplicado
        assert reconciliar(conn, client, kb, config).ja_conhecidos == 1
    conn.commit()
    # A new connection proves persistence, rather than visibility inside one transaction.
    with conectar() as other:
        rows = queries.listar_incidentes(other)
        assert len(rows) == 1
        row = queries.obter_incidente(other, rows[0]["id"])
    plan = row["explicabilidade"]["plano"]
    assert plan["estado"] == "concluido" and plan["opcoes"]
    assert row["decisao_humana"] is None and row["ts_aprovacao"] is None
    assert row["status_execucao"] == "pendente"


@pytest.mark.parametrize("scenario", ["disk_full", "cpu_high", "service_down"])
def test_duplicate_during_inspection_cannot_replace_or_lose_plan(
        conn, kb, config, alerta, configured_inspection, monkeypatch, scenario):
    collecting, release = Event(), Event()
    alert = alerta(scenario, id_evento="concurrent-plan", ip_address="192.0.2.152")

    def collect(_):
        collecting.set()
        assert release.wait(10)
        return diagnostic(scenario)

    monkeypatch.setattr(action_plans, "collect_evidence", collect)

    def first_delivery():
        with conectar() as other:
            return reconciliar(other, SimpleNamespace(alertas_abertos=lambda: [alert]), kb, config)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first_delivery)
        try:
            assert collecting.wait(10)
            duplicate = ingerir(conn, alert, kb, config)
            assert duplicate.duplicado
            row = queries.obter_incidente(conn, duplicate.incidente_id)
            assert row["explicabilidade"]["plano"]["estado"] == "coletando"
            assert not queries.marcar_exibicao(conn, row["id"])
            conn.rollback()
        finally:
            release.set()
        assert future.result(timeout=15).recuperados == 1
    row = queries.obter_incidente(conn, duplicate.incidente_id)
    assert row["explicabilidade"]["plano"]["opcoes"]
    assert row["ts_aprovacao"] is None


@pytest.mark.parametrize("scenario", ["disk_full", "cpu_high", "service_down"])
def test_missing_evidence_produces_explicit_unavailable_plan(
        conn, kb, config, alerta, monkeypatch, scenario):
    monkeypatch.setenv("TARGET_SSH_HOST", "192.0.2.152")
    monkeypatch.setattr(action_plans, "collect_evidence", lambda alert: None)
    get_settings.cache_clear()
    try:
        result = ingerir(conn, alerta(scenario, id_evento="no-target"), kb, config,
                         usar_historico=False)
        row = queries.obter_incidente(conn, result.incidente_id)
        plan = row["explicabilidade"]["plano"]
        assert plan["estado"] == "concluido"
        assert not plan["opcoes"] and "Não foi possível coletar" in plan["aviso"]
        assert row["ts_aprovacao"] is None
    finally:
        get_settings.cache_clear()
