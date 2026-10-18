"""Polling must normalize real Zabbix-shaped metadata like the webhook, not pretyped alerts."""
from dataclasses import asdict

import pytest

from src.db import queries
from src.engine import action_plans
from src.engine.config import get_settings
from src.engine.reconciliacao import reconciliar
from src.engine.zabbix_client import ZabbixClient, ZabbixError, normalizar_webhook

CASES = [
    ("cpu_high", "system.cpu.util", "0", "99.3", "Polaris: High CPU utilization (over 90% for 2m)", "R002"),
    ("disk_full", "vfs.fs.size[/mnt/polaris_test,pused]", "0", "97", "Disk space is critically low", "R001"),
    ("service_down", "proc.num[nginx]", "3", "0", "Service nginx is not running", "R003"),
]


def client_for(monkeypatch, case, *, items=None, samples=None, history_error=False, tags=None):
    _, key, value_type, value, text, _ = case
    client = ZabbixClient(url="http://zabbix.invalid/api_jsonrpc.php", token="fixture")
    tags = tags if tags is not None else [{"tag": "polaris", "value": "enabled"}]
    items = items if items is not None else [
        {"itemid": "50797", "key_": key, "value_type": value_type, "hostid": "10"}]
    samples = samples if samples is not None else [
        {"itemid": "50797", "clock": "1792356753", "ns": "100", "value": value}]
    calls = []

    def call(method, params):
        calls.append((method, params))
        if method == "problem.get":
            return [{"eventid": "745", "objectid": "25281", "clock": "1792356753", "ns": "200",
                     "name": text, "severity": "4", "tags": tags}]
        if method == "event.get":
            return [{"eventid": "745", "hosts": [{"hostid": "10", "host": "vm-alvo"}]}]
        if method == "host.get":
            return [{"hostid": "10", "interfaces": [
                {"type": "1", "main": "1", "useip": "1", "ip": "192.0.2.152"}]}]
        if method == "trigger.get":
            assert params["triggerids"] == ["25281"]
            assert "lastvalue" not in params["selectItems"]
            return [{"triggerid": "25281", "items": items}]
        assert method == "history.get"
        assert params["history"] == int(value_type)
        assert params["time_till"] == 1792356753
        if history_error:
            raise ZabbixError("fixture: history permission denied")
        return samples

    monkeypatch.setattr(client, "_chamar", call)
    return client, calls


@pytest.mark.parametrize("case", CASES)
def test_polling_without_type_tag_matches_every_webhook_motor_field(monkeypatch, case):
    scenario, key, _, value, text, _ = case
    client, _ = client_for(monkeypatch, case)
    polled = client.alertas_abertos()[0]
    webhook = normalizar_webhook({
        "event_id": "745", "host": "vm-alvo", "host_ip": "192.0.2.152", "trigger": text,
        "severity": "4", "event_time": "1792356753", "item_key": key, "item_value": value,
        "tags": [{"tag": "polaris", "value": "enabled"}]})
    assert polled.tipo_alerta == scenario
    assert asdict(polled) == asdict(webhook)


@pytest.mark.parametrize("case", CASES)
def test_actual_polling_creates_expected_rule_and_plan_without_approval(
        conn, kb, config, monkeypatch, case):
    scenario, _, _, _, _, rule = case
    client, _ = client_for(monkeypatch, case)
    monkeypatch.setenv("TARGET_SSH_HOST", "192.0.2.152")
    monkeypatch.setenv("POLARIS_CONFIDENCE_HISTORY", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(action_plans, "collect_evidence", lambda alert: {"erro": "fixture: read unavailable"})
    try:
        assert reconciliar(conn, client, kb, config).recuperados == 1
        rows = queries.listar_incidentes(conn)
        assert len(rows) == 1
        row = queries.obter_incidente(conn, rows[0]["id"])
        assert row["regra_disparada"] == rule
        assert row["explicabilidade"]["plano"]["estado"] == "concluido"
        assert row["status_execucao"] == "pendente"
        assert row["decisao_humana"] is None and row["ts_aprovacao"] is None
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("samples,expected", [
    ([{"itemid": "50797", "clock": "1792356753", "ns": "300", "value": "1"},
      {"itemid": "50797", "clock": "1792356753", "ns": "100", "value": "99.3"}], 99.3),
    ([{"itemid": "50797", "clock": "1792356754", "ns": "0", "value": "1"}], None),
    ([{"itemid": "wrong", "clock": "1792356753", "ns": "100", "value": "1"}], None),
    ([], None),
])
def test_polling_never_uses_future_or_other_item_samples(monkeypatch, samples, expected):
    client, _ = client_for(monkeypatch, CASES[0], samples=samples)
    alert = client.alertas_abertos()[0]
    assert alert.tipo_alerta == "cpu_high"
    assert alert.valor == expected


@pytest.mark.parametrize("items", [[], [
    {"itemid": "1", "key_": "system.cpu.util", "hostid": "10", "value_type": "0"},
    {"itemid": "2", "key_": "proc.num[nginx]", "hostid": "10", "value_type": "3"}], [
    {"itemid": "1", "key_": "system.cpu.util", "hostid": "other", "value_type": "0"}]])
def test_polling_does_not_guess_an_item_from_ambiguous_or_foreign_metadata(monkeypatch, items):
    client, calls = client_for(monkeypatch, CASES[0], items=items)
    alert = client.alertas_abertos()[0]
    assert alert.metrica is None and alert.valor is None and alert.tipo_alerta == "desconhecido"
    assert not any(method == "history.get" for method, _ in calls)


def test_history_permission_failure_keeps_key_and_partial_evidence(monkeypatch):
    client, _ = client_for(monkeypatch, CASES[0], history_error=True)
    alert = client.alertas_abertos()[0]
    assert alert.tipo_alerta == "cpu_high" and alert.metrica == "system.cpu.util"
    assert alert.valor is None


def test_explicit_type_tag_does_not_erase_the_actual_metric_allowlist(monkeypatch, kb):
    from src.engine.inference import match_rules
    client, _ = client_for(monkeypatch, CASES[1], tags=[{"tag": "polaris_tipo", "value": "cpu_high"}])
    alert = client.alertas_abertos()[0]
    assert alert.tipo_alerta == "cpu_high" and alert.metrica.startswith("vfs.fs.size")
    assert not match_rules(alert, kb.regras)
