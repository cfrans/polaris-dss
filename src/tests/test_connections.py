"""Header probes must verify access without SSH, mutations or raw credential errors."""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import routes
from src.engine import diagnostico


@pytest.fixture
def probes(monkeypatch):
    calls = []
    settings = SimpleNamespace(zabbix_url="http://zabbix.invalid/api_jsonrpc.php",
                               zabbix_user="", zabbix_password="", zabbix_token="private-token")
    monkeypatch.setattr(diagnostico, "get_settings", lambda: settings)
    monkeypatch.setattr(diagnostico, "_verificar_alvo", lambda: pytest.fail("must not run SSH"))

    @contextmanager
    def connect(**kwargs):
        assert kwargs == {"connect_timeout": 3}

        @contextmanager
        def cursor():
            yield SimpleNamespace(execute=lambda sql: calls.append(sql))

        yield SimpleNamespace(cursor=cursor)

    monkeypatch.setattr("src.db.connection.conectar", connect)

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        assert kwargs["timeout"] == 3
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": []},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr("src.engine.zabbix_client.httpx.post", post)
    return settings, calls


def test_connections_validate_token_and_only_read_one_host_and_database(probes):
    _, calls = probes
    data = diagnostico.check_connections()
    assert {check["id"]: check["estado"] for check in data["verificacoes"]} == {"banco": "ok", "zabbix": "ok"}
    assert calls == ["SELECT 1", {"jsonrpc": "2.0", "method": "host.get",
                                "params": {"output": ["hostid"], "limit": 1}, "id": 1}]
    assert datetime.fromisoformat(data["verificado_em"]).utcoffset().total_seconds() == 0
    assert "private-token" not in str(data)


@pytest.mark.parametrize("failure", ["token", "network", "database"])
def test_failed_probe_does_not_hide_other_dependency_or_expose_raw_errors(probes, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise RuntimeError("private-token and secret error detail")

    if failure == "database":
        monkeypatch.setattr("src.db.connection.conectar", fail)
    elif failure == "network":
        monkeypatch.setattr("src.engine.zabbix_client.httpx.post", fail)
    else:
        monkeypatch.setattr("src.engine.zabbix_client.httpx.post", lambda url, **kwargs: httpx.Response(
            200, json={"error": {"message": "private-token rejected"}}, request=httpx.Request("POST", url)))
    data = diagnostico.check_connections()
    states = {check["id"]: check["estado"] for check in data["verificacoes"]}
    assert states["banco"] == ("falha" if failure == "database" else "ok")
    assert states["zabbix"] == ("ok" if failure == "database" else "falha")
    assert "private-token" not in str(data)
    assert "secret error detail" not in str(data)


@pytest.mark.parametrize("configured,expected", [(False, "nao_configurado"), (True, "aviso")])
def test_unconfigured_zabbix_is_not_green_and_makes_no_network_call(probes, configured, expected):
    settings, calls = probes
    settings.zabbix_token = ""
    if not configured:
        settings.zabbix_url = ""
    data = diagnostico.check_connections()
    assert data["verificacoes"][1]["estado"] == expected
    assert calls == ["SELECT 1"]


def test_password_authentication_is_checked_before_host_probe(probes, monkeypatch):
    settings, calls = probes
    settings.zabbix_token = ""
    settings.zabbix_user, settings.zabbix_password = "operator", "private-password"

    def post(url, **kwargs):
        method = kwargs["json"]["method"]
        calls.append(method)
        if method == "host.get":
            assert kwargs["headers"]["Authorization"] == "Bearer session-token"
        return httpx.Response(200, json={"result": "session-token" if method == "user.login" else []},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr("src.engine.zabbix_client.httpx.post", post)
    data = diagnostico.check_connections()
    assert calls == ["SELECT 1", "user.login", "host.get"]
    assert data["verificacoes"][1]["estado"] == "ok"
    assert "private-password" not in str(data)


def test_connectivity_endpoint_is_available_without_database_dependency(probes):
    app = FastAPI()
    app.include_router(routes.router)
    response = TestClient(app).get("/api/v1/conectividade")
    assert response.status_code == 200
    assert set(response.json()) == {"verificado_em", "verificacoes"}
