"""Optional HTTP pairing on the laboratory network, with real PostgreSQL sessions."""
import secrets

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.engine import pairing
from src.engine.config import get_settings
from src.engine.setup_vault import Vault

LAN = 'http://192.0.2.20'
LAN_HEADERS = {'Origin': LAN, 'X-Polaris-Auth': '1'}
LOCAL_HEADERS = {'Origin': 'http://127.0.0.1', 'X-Polaris-Auth': '1'}


@pytest.fixture
def lab(conn, tmp_path, monkeypatch):
    def configure(enabled):
        monkeypatch.setenv('POLARIS_PAREAMENTO_HTTP', 'true' if enabled else 'false')
        get_settings.cache_clear()
    conn.execute('TRUNCATE usuarios, pareamentos CASCADE')
    conn.execute('UPDATE auth_limite SET tentativas=0,janela=now()')
    conn.commit()
    monkeypatch.setenv('POLARIS_SETUP_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('POLARIS_SETUP_KEY_FILE', str(tmp_path / 'key'))
    configure(False)
    code = Vault(tmp_path / 'data', tmp_path / 'key').initialize()
    password = secrets.token_urlsafe(24)
    with TestClient(app, base_url='http://127.0.0.1') as local:
        assert local.post('/api/v1/auth/bootstrap', headers=LOCAL_HEADERS, json={
            'username': 'lab-admin', 'name': 'Lab admin', 'password': password, 'code': code}).status_code == 201
    with TestClient(app, base_url=LAN) as client:
        yield client, conn, password, configure
    get_settings.cache_clear()


def test_codes_are_short_unambiguous_and_normalized():
    code = pairing.new_code()
    assert len(code) == 9 and code[4] == '-'
    assert set(code.replace('-', '')) <= set(pairing.ALPHABET)
    assert not set('01IO') & set(code)
    assert pairing.normalize(' abcd-efgh ') == 'ABCDEFGH'


def test_instructions_print_tunnel_when_disabled_and_code_when_enabled():
    tunnel = '\n'.join(pairing.access_instructions(8000, False, '172.30.58.23', 'caio'))
    assert 'ssh -N -L 8000:localhost:8000 caio@172.30.58.23' in tunnel
    assert 'POLARIS_PAREAMENTO_HTTP' in tunnel and 'Código' not in tunnel
    paired = '\n'.join(pairing.access_instructions(8080, True, '172.30.58.23', '', 'ABCD-EFGH'))
    assert 'http://172.30.58.23:8080/login.html' in paired and 'ABCD-EFGH' in paired
    assert 'sem criptografia' in paired
    assert '--address' in '\n'.join(pairing.access_instructions(8000, True))


def test_disabled_pairing_keeps_http_blocked_and_pages_redirect_to_login(lab):
    client, _, password, _ = lab
    assert client.get('/api/v1/auth/pareamento').json()['state'] == 'blocked'
    assert client.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': 'ABCD-EFGH'}).status_code == 403
    assert client.post('/api/v1/auth/entrar', headers=LAN_HEADERS,
                       json={'username': 'lab-admin', 'password': password}).status_code == 403
    page = client.get('/configuracao.html', follow_redirects=False)
    assert page.status_code == 303 and page.headers['location'].startswith('/login.html')


def test_single_use_code_pairs_one_browser_before_login(lab):
    client, _, password, configure = lab
    configure(True)
    assert client.get('/api/v1/auth/pareamento').json()['state'] == 'required'
    assert client.post('/api/v1/auth/entrar', headers=LAN_HEADERS,
                       json={'username': 'lab-admin', 'password': password}).status_code == 403
    code = pairing.issue_code()
    assert client.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': 'ZZZZ-ZZZZ'}).status_code == 401
    assert client.post('/api/v1/auth/pareamento', headers={'Origin': LAN},
                       json={'code': code}).status_code == 403
    paired = client.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': code.lower().replace('-', '')})
    assert paired.status_code == 200
    cookie = paired.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and pairing.COOKIE in cookie
    assert client.get('/api/v1/auth/pareamento').json()['state'] == 'paired'
    assert client.post('/api/v1/auth/entrar', headers=LAN_HEADERS,
                       json={'username': 'lab-admin', 'password': password}).status_code == 200
    assert client.get('/api/v1/auth/sessao').json()['authenticated'] is True
    with TestClient(app, base_url=LAN) as other:
        assert other.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': code}).status_code == 401
        assert other.get('/api/v1/auth/pareamento').json()['state'] == 'required'


def test_expired_codes_and_pairings_stop_working_and_can_be_revoked(lab):
    client, conn, _, configure = lab
    configure(True)
    stale = pairing.issue_code()
    conn.execute("UPDATE pareamentos SET ts_expiracao_codigo=now()-interval '1 second'")
    conn.commit()
    assert client.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': stale}).status_code == 401
    assert client.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': pairing.issue_code()}).status_code == 200
    assert client.get('/api/v1/auth/pareamento').json()['state'] == 'paired'
    conn.execute("UPDATE pareamentos SET ts_expiracao=now()-interval '1 second' WHERE token_hash IS NOT NULL")
    conn.commit()
    assert client.get('/api/v1/auth/pareamento').json()['state'] == 'required'
    assert client.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': pairing.issue_code()}).status_code == 200
    assert pairing.revoke_all() >= 1
    assert client.get('/api/v1/auth/pareamento').json()['state'] == 'required'


def test_disabling_the_flag_ignores_existing_pairings(lab):
    client, _, _, configure = lab
    configure(True)
    assert client.post('/api/v1/auth/pareamento', headers=LAN_HEADERS, json={'code': pairing.issue_code()}).status_code == 200
    configure(False)
    assert client.get('/api/v1/auth/pareamento').json()['state'] == 'blocked'
    assert client.get('/api/v1/auth/sessao').status_code == 403


def test_loopback_and_https_never_need_pairing(lab):
    _, _, _, configure = lab
    configure(True)
    with TestClient(app, base_url='http://127.0.0.1') as local:
        assert local.get('/api/v1/auth/pareamento').json()['state'] == 'secure'
    with TestClient(app, base_url='https://polaris.example') as tls:
        assert tls.get('/api/v1/auth/pareamento').json()['state'] == 'secure'
