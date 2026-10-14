"""Real ingestion paths must preserve target identity required by experiment linking."""

from datetime import datetime, timezone

import pytest

from src.db import queries
from src.engine.models import Alert
from src.engine.zabbix_client import ZabbixClient, normalizar_webhook
from experiment import rounds


@pytest.mark.parametrize("raw,expected", [
    (" 192.0.2.152 ", "192.0.2.152"), ("2001:0db8::0152", "2001:db8::152"),
    (None, None), ("", None), ("{HOST.IP}", None), ("target.example", None),
    ("192.0.2.999", None), ("192.0.2.152/24", None), ("fe80::1%eth0", None),
    (123, None), (True, None),
])
def test_normalization_keeps_only_literal_addresses_without_dns_or_losing_alert(raw, expected):
    alert = normalizar_webhook({"host": "target", "host_ip": raw, "event_id": "identity"})
    assert alert.hostname == "target"
    assert alert.ip_address == expected
    assert Alert.from_dict({"tipo_alerta": "unknown", "hostname": "target", "ip_address": raw}).ip_address == expected


def polling_client(monkeypatch, interfaces, event_hosts=None):
    client = ZabbixClient(url="http://zabbix.invalid/api_jsonrpc.php", token="test-token")
    event_hosts = event_hosts if event_hosts is not None else [{"hostid": "10", "host": "target"}]
    calls = []

    def call(method, params):
        calls.append((method, params))
        if method == "problem.get":
            return [{"eventid": "identity", "name": "Service nginx is not running", "severity": "4",
                     "clock": str(int(datetime.now(timezone.utc).timestamp())),
                     "tags": [{"tag": "polaris_tipo", "value": "service_down"}]}]
        if method == "event.get":
            assert params["selectHosts"] == ["hostid", "host"]
            return [{"eventid": "identity", "hosts": event_hosts}]
        assert method == "host.get"
        assert params["hostids"] == ["10"]
        return [{"hostid": "10", "interfaces": interfaces}]

    monkeypatch.setattr(client, "_chamar", call)
    return client, calls


@pytest.mark.parametrize("interfaces,expected", [
    ([{"ip": "192.0.2.152", "type": "1", "main": "1", "useip": "1"}], "192.0.2.152"),
    ([{"ip": "192.0.2.9", "type": "2", "main": "1", "useip": "1"},
      {"ip": "2001:db8::152", "type": "1", "main": "1", "useip": "1"}], "2001:db8::152"),
    ([{"ip": "192.0.2.152", "type": "1", "main": "1", "useip": "0"}], None),
    ([{"ip": "bad", "type": "1", "main": "1", "useip": "1"}], None),
    ([{"ip": "192.0.2.152", "type": "1", "main": "1", "useip": "1"}] * 2, None),
    ([], None),
])
def test_polling_uses_only_unambiguous_primary_agent_interface(monkeypatch, interfaces, expected):
    client, _ = polling_client(monkeypatch, interfaces)
    assert client.alertas_abertos()[0].ip_address == expected


def test_multi_host_event_does_not_guess_an_address(monkeypatch):
    client, calls = polling_client(monkeypatch, [], [{"hostid": "10", "host": "target"},
                                                   {"hostid": "11", "host": "other"}])
    assert client.alertas_abertos()[0].ip_address is None
    assert [method for method, _ in calls] == ["problem.get", "event.get"]


@pytest.mark.parametrize("source", ["webhook", "polling"])
def test_actual_ingestion_persists_ip_and_links_to_ip_target_without_approval_or_execution(cliente, conn, kb, config, monkeypatch, source):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO experiment_run (cenario, braco, rodada, versao_kb, host_alvo, ts_injecao)
                       VALUES ('service_down', 'hitl', 1, %s, '192.0.2.152', NOW() - INTERVAL '1 day')
                       RETURNING id""", (kb.versao_kb,))
        run_id = cur.fetchone()["id"]
    conn.commit()
    if source == "webhook":
        monkeypatch.setattr(cliente.app.state.settings, "polaris_webhook_token", "test-token")
        response = cliente.post("/webhook/zabbix", headers={"X-Polaris-Token": "test-token"}, json={
            "event_id": "identity", "event_time": int(datetime.now(timezone.utc).timestamp()),
            "host": "target", "host_ip": "192.0.2.152", "severity": "High",
            "item_key": "proc.num[nginx]", "item_value": "0", "trigger": "Service nginx is not running",
            "tags": {"polaris_tipo": "service_down"},
        })
        assert response.status_code == 201
        assert response.json()["status"] == "created", response.json()
        incident_id = response.json()["incidente_id"]
    else:
        from src.engine.reconciliacao import reconciliar
        client, _ = polling_client(monkeypatch, [{"ip": "192.0.2.152", "type": "1", "main": "1", "useip": "1"}])
        assert reconciliar(conn, client, kb, config).recuperados == 1
        incident_id = queries.listar_incidentes(conn)[0]["id"]
        conn.commit()
    assert cliente.get(f"/api/v1/incidentes/{incident_id}").json()["ip_address"] == "192.0.2.152"
    conn.rollback()
    assert rounds.link_incident(conn, run_id, incident_id, "identity") is True
    row = queries.obter_incidente(conn, incident_id)
    assert str(row["ip_address"]) == "192.0.2.152"
    assert row["experiment_run_id"] == run_id
    assert row["decisao_humana"] is None
    assert row["ts_aprovacao"] is None
    assert row["ts_exibicao"] is None
    assert row["status_execucao"] == "pendente"


def test_unmatched_alert_keeps_identity_but_invalid_address_still_cannot_link(conn, kb, config):
    from src.engine.service import ingerir
    first = ingerir(conn, normalizar_webhook({"host": "target", "host_ip": "192.0.2.152", "event_id": "unmatched"}),
                    kb, config, usar_historico=False)
    assert str(queries.obter_incidente(conn, first.incidente_id)["ip_address"]) == "192.0.2.152"
    invalid = ingerir(conn, normalizar_webhook({"host": "target", "host_ip": "invalid", "event_id": "invalid"}),
                      kb, config, usar_historico=False)
    row = queries.obter_incidente(conn, invalid.incidente_id)
    assert row["ip_address"] is None
    assert rounds.target_matches("192.0.2.152", row) is False
