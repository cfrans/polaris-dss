"""Server gauges must use recent samples from the configured host, never the remediation target."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.engine import server_metrics as metrics


@pytest.fixture
def telemetry(monkeypatch):
    settings = SimpleNamespace(polaris_zabbix_host="polaris-server", zabbix_url="http://zabbix.invalid",
                               zabbix_user="", zabbix_password="", zabbix_token="private-token")
    monkeypatch.setattr(metrics, "get_settings", lambda: settings)
    clock = int(datetime.now(timezone.utc).timestamp()) - 1
    items = [{"key_": key, "lastvalue": value, "lastclock": str(clock), "status": "0", "state": "0"}
             for key, value in [("system.cpu.util[,idle]", "80"), ("vm.memory.size[pavailable]", "60")]]
    calls = []

    def call(self, method, params):
        assert self.timeout == 3
        calls.append((method, params))
        if method == "host.get":
            return [{"hostid": "151", "host": "polaris-server", "status": "0"}]
        assert method == "item.get", "must not read events or mutate Zabbix"
        return items

    monkeypatch.setattr(metrics.ZabbixClient, "_chamar", call)
    return settings, items, calls


def test_reads_only_configured_host_and_inverts_idle_and_available_memory(telemetry):
    _, _, calls = telemetry
    data = metrics.get_server_metrics()
    assert data["estado"] == "ok"
    assert data["cpu"]["percentual"] == 20
    assert data["memoria"]["percentual"] == 40
    assert calls[0][1]["filter"] == {"host": ["polaris-server"]}
    assert calls[1][1]["hostids"] == ["151"]
    assert "private-token" not in str(data)


@pytest.mark.parametrize("field,value", [("lastvalue", "NaN"), ("lastvalue", "inf"),
    ("lastvalue", "-1"), ("lastvalue", "101"), ("lastvalue", "broken"),
    ("lastclock", "0"), ("lastclock", "invalid"), ("state", "1"), ("status", "1")])
def test_invalid_or_unsupported_cpu_never_becomes_zero(telemetry, field, value):
    _, items, _ = telemetry
    items[0][field] = value
    data = metrics.get_server_metrics()
    assert data["estado"] == "parcial"
    assert data["cpu"] is None
    assert data["memoria"]["percentual"] == 40


@pytest.mark.parametrize("offset", [-301, 60])
def test_stale_or_future_clock_is_unavailable(telemetry, offset):
    _, items, _ = telemetry
    items[0]["lastclock"] = str(int(datetime.now(timezone.utc).timestamp()) + offset)
    assert metrics.get_server_metrics()["cpu"] is None


def test_actual_zero_and_full_cpu_are_valid_measurements(telemetry):
    _, items, _ = telemetry
    for idle, expected in [("100", 0), ("0", 100)]:
        items[0]["lastvalue"] = idle
        assert metrics.get_server_metrics()["cpu"]["percentual"] == expected


def test_duplicate_item_and_bare_cpu_key_cannot_masquerade_as_total_usage(telemetry):
    _, items, _ = telemetry
    items.append(dict(items[0]))
    assert metrics.get_server_metrics()["cpu"] is None
    items[:] = [{**items[0], "key_": "system.cpu.util"}]
    assert metrics.get_server_metrics()["estado"] == "sem_dados"


def test_memory_utilization_has_precedence_over_available_fallback(telemetry):
    _, items, _ = telemetry
    items.append({**items[1], "key_": "vm.memory.utilization", "lastvalue": "44.3"})
    assert metrics.get_server_metrics()["memoria"]["percentual"] == 44.3


@pytest.mark.parametrize("field", ["polaris_zabbix_host", "zabbix_url", "zabbix_token"])
def test_missing_configuration_makes_no_network_call(telemetry, field):
    settings, _, calls = telemetry
    setattr(settings, field, "")
    data = metrics.get_server_metrics()
    assert data["cpu"] is None and data["memoria"] is None
    assert calls == []
    assert data["estado"] != "ok"


@pytest.mark.parametrize("hosts", [[], [{"hostid": "152", "host": "target", "status": "0"}],
    [{"hostid": "151", "host": "polaris-server", "status": "1"}]])
def test_absent_wrong_or_disabled_host_does_not_read_items(telemetry, monkeypatch, hosts):
    calls = []
    monkeypatch.setattr(metrics.ZabbixClient, "_chamar", lambda self, method, params: calls.append(method) or hosts)
    assert metrics.get_server_metrics()["estado"] == "indisponivel"
    assert calls == ["host.get"]


def test_upstream_failure_is_sanitized(telemetry, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-token: secret response")
    monkeypatch.setattr(metrics.ZabbixClient, "_chamar", fail)
    data = metrics.get_server_metrics()
    assert data["estado"] == "indisponivel"
    assert "private-token" not in str(data) and "secret response" not in str(data)


def test_http_endpoint_has_no_database_or_remediation_dependency(telemetry):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/v1/servidor")
    assert response.status_code == 200
    assert response.json()["host"] == "polaris-server"
    assert response.json()["cpu"]["percentual"] == 20
