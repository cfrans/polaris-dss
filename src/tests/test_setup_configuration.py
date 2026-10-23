"""Security boundaries for the encrypted interactive setup."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.api import setup_access
from src.engine.config import get_settings
from src.engine.setup_vault import Vault, VaultError, operation_guard

HEADERS = {"Origin": "http://127.0.0.1", "X-Polaris-Setup": "1"}


@pytest.fixture
def setup_client(tmp_path, monkeypatch, conn):
    directory, key = tmp_path / "data", tmp_path / "key" / "master.key"
    monkeypatch.setenv("POLARIS_SETUP_DIR", str(directory))
    monkeypatch.setenv("POLARIS_SETUP_KEY_FILE", str(key))
    get_settings.cache_clear()
    vault = Vault(directory, key)
    code = vault.initialize()
    setup_access.SESSIONS.clear()
    setup_access.ATTEMPTS.clear()
    monkeypatch.setattr("src.api.setup_configuration.ensure_idle", lambda: None)
    import secrets
    from src.api.auth import password_hash
    password = secrets.token_urlsafe(24)
    conn.execute('TRUNCATE usuarios CASCADE')
    conn.execute("UPDATE auth_limite SET tentativas=0,janela=now()")
    conn.execute("INSERT INTO usuarios(login,nome,senha_hash,perfil) VALUES('setup-admin','Setup admin',%s,'admin')", (password_hash(password),))
    conn.commit()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/v1/auth/entrar", json={"username":"setup-admin","password":password}, headers={**HEADERS,'X-Polaris-Auth':'1'}).status_code == 200
        yield client, vault, password
    get_settings.cache_clear()
    setup_access.SESSIONS.clear()
    setup_access.ATTEMPTS.clear()


def test_vault_encrypts_and_refuses_tampering_or_missing_key(tmp_path):
    vault = Vault(tmp_path / "data", tmp_path / "key")
    vault.initialize()
    vault.update(lambda data: data["settings"].update(zabbix_token="secret-not-on-disk"))
    assert b"secret-not-on-disk" not in vault.path.read_bytes()
    assert vault.read()["settings"]["zabbix_token"] == "secret-not-on-disk"
    old = vault.path.read_bytes()
    with pytest.raises(VaultError):
        vault.initialize()
    assert vault.path.read_bytes() == old
    vault.path.write_bytes(b"invalid-ciphertext")
    with pytest.raises(VaultError):
        vault.read()
    vault.path.write_bytes(old)
    vault.key_file.unlink()
    with pytest.raises(VaultError):
        vault.read()
    assert vault.path.read_bytes() == old


def test_vault_rejects_stale_updates_and_concurrent_operations(tmp_path):
    vault = Vault(tmp_path / "data", tmp_path / "key")
    vault.initialize()
    revision = vault.read()["revision"]
    vault.update(lambda data: data["settings"].update(zabbix_url="example"))
    with pytest.raises(VaultError):
        vault.update(lambda data: data.clear(), revision=revision)
    with operation_guard(vault):
        with pytest.raises(VaultError):
            with operation_guard(vault, exclusive=True):
                pytest.fail("must not overlap a live API operation")


def test_auth_origin_logout_and_no_secret_readback(setup_client, monkeypatch):
    client, vault, _ = setup_client
    vault.update(lambda data: data["settings"].update(zabbix_token="never-return-me"))
    response = client.get("/api/v1/instalacao/configuracao")
    assert response.status_code == 200
    assert "never-return-me" not in response.text
    assert response.json()["zabbix"]["token_available"] is True
    assert response.headers["cache-control"] == "no-store"
    assert client.post("/api/v1/instalacao/ssh/chave", headers={**HEADERS, "Origin": "https://other.example"}).status_code == 403
    assert client.post("/api/v1/instalacao/ssh/chave", headers={"Origin": HEADERS["Origin"]}).status_code == 403
    assert client.post("/api/v1/instalacao/sair", headers=HEADERS).status_code == 200
    assert client.get("/api/v1/instalacao/configuracao").status_code == 401


def test_unencrypted_remote_transport_is_rejected(setup_client):
    client, vault, code = setup_client
    response = client.post("http://192.0.2.20/api/v1/instalacao/acesso", json={"code": code},
                           headers={**HEADERS, "Origin": "http://192.0.2.20"})
    assert response.status_code == 403


def test_sensitive_api_calls_require_session_and_legacy_code_cannot_login(setup_client):
    client, vault, _ = setup_client
    assert client.post('/api/v1/regras/reload', headers={**HEADERS,'Origin':'https://other.example'}).status_code == 403
    assert client.post('/api/v1/instalacao/acesso', json={'code':'legacy'}, headers=HEADERS).status_code == 410
    client.cookies.clear()
    assert client.post('/api/v1/regras/reload', headers=HEADERS).status_code == 401


def test_session_expiry_and_attempt_limit(setup_client, conn):
    client, _, password = setup_client
    conn.execute("UPDATE sessoes SET ts_atividade=now()-interval '16 minutes'")
    conn.commit()
    assert client.get('/api/v1/instalacao/configuracao').status_code == 401
    for _ in range(19):
        assert client.post('/api/v1/auth/entrar',json={'username':'setup-admin','password':'wrong'},headers={**HEADERS,'X-Polaris-Auth':'1'}).status_code == 401
    assert client.post('/api/v1/auth/entrar',json={'username':'setup-admin','password':password},headers={**HEADERS,'X-Polaris-Auth':'1'}).status_code == 429


def test_environment_import_does_not_return_url_credentials(setup_client, monkeypatch):
    client, _, _ = setup_client
    monkeypatch.setenv("ZABBIX_URL", "https://login:secret@example.test/api_jsonrpc.php?token=hidden")
    monkeypatch.setenv("ZABBIX_TOKEN", "environment-secret")
    get_settings.cache_clear()
    response = client.get("/api/v1/instalacao/configuracao?source=environment")
    assert response.status_code == 200
    assert response.json()["zabbix"]["url"] == "https://example.test/api_jsonrpc.php"
    assert "secret" not in response.text and "hidden" not in response.text


def test_failed_test_cannot_save_and_receipt_cannot_replay(setup_client, monkeypatch):
    client, vault, _ = setup_client
    class Zabbix:
        def __init__(self, **kwargs): self.values = kwargs
        def versao(self): return "7.0.99"
        def check_access(self): pass
    monkeypatch.setattr("src.api.setup_configuration.ZabbixClient", Zabbix)
    body = {"url": "https://zabbix.example", "mode": "token", "token": "api-secret",
            "webhook_token": "x" * 32}
    response = client.post("/api/v1/instalacao/zabbix/testar", json=body, headers=HEADERS)
    receipt = response.json()["receipt"]
    assert "api-secret" not in response.text
    saved = client.post("/api/v1/instalacao/zabbix/salvar", json={"receipt": receipt}, headers=HEADERS)
    assert saved.status_code == 200
    assert get_settings().zabbix_token == "api-secret"
    assert b"api-secret" not in vault.path.read_bytes()
    assert client.post("/api/v1/instalacao/zabbix/salvar", json={"receipt": receipt}, headers=HEADERS).status_code == 409
    Zabbix.check_access = lambda self: (_ for _ in ()).throw(ValueError("api-secret"))
    failed = client.post("/api/v1/instalacao/zabbix/testar", json=body, headers=HEADERS)
    assert failed.status_code == 422 and "api-secret" not in failed.text
    assert client.post("/api/v1/instalacao/zabbix/salvar", json={"receipt": receipt}, headers=HEADERS).status_code == 409


def test_stale_revision_and_expired_proofs_are_rejected(setup_client, monkeypatch):
    client, vault, _ = setup_client
    class Zabbix:
        def __init__(self, **kwargs): pass
        def versao(self): return "7.0.99"
        def check_access(self): pass
    monkeypatch.setattr("src.api.setup_configuration.ZabbixClient", Zabbix)
    body = {"url": "https://example.test", "mode": "token", "token": "secret", "webhook_token": "x" * 32}
    receipt = client.post("/api/v1/instalacao/zabbix/testar", json=body, headers=HEADERS).json()["receipt"]
    vault.update(lambda data: data.update(extra="new-revision"))
    assert client.post("/api/v1/instalacao/zabbix/salvar", json={"receipt": receipt}, headers=HEADERS).status_code == 409
    receipt = client.post("/api/v1/instalacao/zabbix/testar", json=body, headers=HEADERS).json()["receipt"]
    next(iter(setup_access.SESSIONS.values()))["proofs"]["zabbix"]["expires"] = 0
    assert client.post("/api/v1/instalacao/zabbix/salvar", json={"receipt": receipt}, headers=HEADERS).status_code == 409


def test_draft_ssh_key_is_encrypted_and_only_public_half_returned(setup_client):
    client, vault, _ = setup_client
    response = client.post("/api/v1/instalacao/ssh/chave", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["public_key"].startswith("ssh-ed25519 ")
    assert "PRIVATE KEY" not in response.text
    assert "PRIVATE KEY" in vault.read()["draft_ssh_private_key"]
    assert b"PRIVATE KEY" not in vault.path.read_bytes()


def test_ssh_pin_mismatch_never_authenticates_and_tested_key_is_saved(setup_client, monkeypatch):
    client, vault, _ = setup_client
    from src.engine.setup_connections import generate_key, read_private_key
    private, public = generate_key()
    host_key = read_private_key(private)
    fingerprint = "SHA256:" + "A" * 43
    monkeypatch.setattr("src.api.setup_configuration.inspect_host", lambda host: (host_key, fingerprint))
    calls = []
    monkeypatch.setattr("src.api.setup_configuration.test_ssh", lambda *args: calls.append(args))
    client.post("/api/v1/instalacao/ssh/chave", headers=HEADERS)
    body = {"host": "192.0.2.1", "user": "polaris", "generated_key": True,
            "expected_fingerprint": "SHA256:" + "B" * 43}
    assert client.post("/api/v1/instalacao/ssh/testar", json=body, headers=HEADERS).status_code == 422
    assert calls == []
    body["expected_fingerprint"] = fingerprint
    tested = client.post("/api/v1/instalacao/ssh/testar", json=body, headers=HEADERS)
    assert tested.status_code == 200 and len(calls) == 1
    saved = client.post("/api/v1/instalacao/ssh/salvar", json={"receipt": tested.json()["receipt"]}, headers=HEADERS)
    assert saved.status_code == 200
    assert get_settings().target_ssh_key_path == "@cofre"
    assert vault.read()["ssh_private_key"] == calls[0][2]
    assert "draft_ssh_private_key" not in vault.read()
    assert b"PRIVATE KEY" not in vault.path.read_bytes()


def test_proof_belongs_to_session_and_never_accepts_changed_body(setup_client, monkeypatch):
    client, vault, code = setup_client
    class Zabbix:
        def __init__(self, **kwargs): pass
        def versao(self): return "7.0.99"
        def check_access(self): pass
    monkeypatch.setattr("src.api.setup_configuration.ZabbixClient", Zabbix)
    receipt = client.post("/api/v1/instalacao/zabbix/testar", headers=HEADERS,
        json={"url": "https://example.test", "mode": "token", "token": "tested-secret", "webhook_token": "x" * 32}).json()["receipt"]
    client.post("/api/v1/auth/sair", headers={**HEADERS,"X-Polaris-Auth":"1"})
    client.post("/api/v1/auth/entrar", json={"username":"setup-admin","password":code}, headers={**HEADERS,"X-Polaris-Auth":"1"})
    assert client.post("/api/v1/instalacao/zabbix/salvar", json={"receipt": receipt}, headers=HEADERS).status_code == 409
    assert vault.read()["settings"] == {}


@pytest.mark.parametrize("pending", [True, False])
def test_configuration_change_fails_closed_for_open_incident_or_database_failure(monkeypatch, pending):
    from src.api.setup_configuration import ensure_idle
    from fastapi import HTTPException
    from contextlib import contextmanager
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql):
            assert "'pendente','executando'" in sql
        def fetchone(self): return (1,)
    class Connection:
        def cursor(self): return Cursor()
    @contextmanager
    def connect(**kwargs):
        if not pending: raise OSError("unavailable")
        yield Connection()
    monkeypatch.setattr("src.db.connection.conectar", connect)
    with pytest.raises(HTTPException) as error:
        ensure_idle()
    assert error.value.status_code == (409 if pending else 503)


@pytest.mark.parametrize("interval, status", [(0, 200), (1, 422), (5, 200)])
def test_polling_can_pause_or_resume_but_never_accepts_unsafe_short_interval(setup_client, interval, status):
    client, vault, _ = setup_client
    vault.update(lambda data: data.update(validation={"zabbix": {"at": time.time()}}))
    response = client.post("/api/v1/instalacao/reconciliacao", json={"interval": interval}, headers=HEADERS)
    assert response.status_code == status
    if status == 200:
        assert get_settings().polaris_polling_segundos == interval


def test_ssh_test_times_out_when_peer_never_reports_exit_status(monkeypatch):
    from src.engine import setup_connections as connections
    from types import SimpleNamespace
    import paramiko
    _, public = connections.generate_key()
    host_entry = paramiko.hostkeys.HostKeyEntry.from_line("192.0.2.1 " + public)
    closed = []
    class Client:
        def set_missing_host_key_policy(self, policy): pass
        def get_host_keys(self): return paramiko.HostKeys()
        def connect(self, *args, **kwargs): pass
        def exec_command(self, command, timeout):
            assert command == "true"
            return None, SimpleNamespace(channel=SimpleNamespace(exit_status_ready=lambda: False)), None
        def close(self): closed.append(True)
    monkeypatch.setattr(connections.paramiko, "SSHClient", Client)
    ticks = iter([0, 5])
    monkeypatch.setattr(connections.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        connections.test_ssh("192.0.2.1", "polaris", "", "192.0.2.1 " + public, "/unused")
    assert closed == [True]
