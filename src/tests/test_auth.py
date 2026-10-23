"""Authentication boundary with real PostgreSQL sessions, without business auth mocks."""
import secrets
import pytest
from fastapi.testclient import TestClient
from src.api.server import app
from src.api import auth
from src.engine.config import get_settings
from src.engine.setup_vault import Vault

HEADERS={'Origin':'http://127.0.0.1','X-Polaris-Auth':'1','X-Polaris-Setup':'1'}

@pytest.fixture
def access(conn,tmp_path,monkeypatch):
    conn.execute('TRUNCATE usuarios CASCADE')
    conn.execute('UPDATE auth_limite SET tentativas=0,janela=now()')
    conn.commit()
    monkeypatch.setenv('POLARIS_SETUP_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('POLARIS_SETUP_KEY_FILE',str(tmp_path/'key'))
    monkeypatch.setenv('TARGET_SSH_HOST','')
    monkeypatch.setenv('POLARIS_DEBUG','true')
    get_settings.cache_clear()
    code=Vault(tmp_path/'data',tmp_path/'key').initialize()
    password=secrets.token_urlsafe(24)
    with TestClient(app,base_url='http://127.0.0.1') as client:
        yield client,conn,code,password
    get_settings.cache_clear()

def bootstrap(access):
    client,conn,code,password=access
    response=client.post('/api/v1/auth/bootstrap',headers=HEADERS,json={'username':'admin-test','name':'Admin Test','password':password,'code':code})
    assert response.status_code==201,response.text
    sign_in(client,'admin-test',password)
    return client,conn,password

def sign_in(client,username,password):
    response=client.post('/api/v1/auth/entrar',headers=HEADERS,json={'username':username,'password':password})
    assert response.status_code==200,response.text


def test_audit_requires_real_session_and_allows_operator_read_only(access):
    client,conn,code,password=access
    paths=['/api/v1/auditoria','/api/v1/auditoria/1','/api/v1/auditoria/exportar?formato=json']
    for path in paths:
        assert client.get(path).status_code==401
    page=client.get('/auditoria.html',follow_redirects=False)
    assert page.status_code==303 and page.headers['location'].endswith('next=/auditoria.html')
    bootstrap(access)
    operator_password=secrets.token_urlsafe(24)
    assert client.post('/api/v1/auth/usuarios',headers=HEADERS,json={
        'username':'audit-reader','name':'Audit reader','password':operator_password,'role':'operador'}).status_code==201
    sign_in(client,'audit-reader',operator_password)
    assert client.get('/auditoria.html').status_code==200
    assert client.get(paths[0]).status_code==200
    assert client.get(paths[1]).status_code==404
    assert client.get(paths[2]).status_code==200
    assert client.post('/api/v1/auditoria',headers=HEADERS,json={}).status_code==405

def test_bootstrap_is_single_use_and_has_no_default_login(access):
    client,conn,code,password=access
    assert client.get('/api/v1/auth/sessao').json()['bootstrap_required'] is True
    assert client.get('/api/v1/incidentes').status_code==401
    assert client.get('/',follow_redirects=False).status_code==303
    assert client.post('/api/v1/auth/bootstrap',headers=HEADERS,json={'username':'admin-test','name':'Test','password':password,'code':'invalid'}).status_code==401
    bootstrap(access)
    row=conn.execute('SELECT * FROM usuarios').fetchone()
    assert row['senha_hash'].startswith('$argon2id$') and password not in row['senha_hash']
    assert client.post('/api/v1/auth/bootstrap',headers=HEADERS,json={'username':'other-admin','name':'Test','password':password,'code':code}).status_code==409
    assert client.post('/api/v1/instalacao/acesso',headers=HEADERS,json={'code':code}).status_code==410


def test_preferences_page_and_legacy_account_keep_real_role_boundaries(access):
    client,conn,code,password=access
    for path in ['/preferencias.html','/contas.html']:
        response=client.get(path,follow_redirects=False)
        assert response.status_code==303
        assert response.headers['location']=='/login.html?next='+path
    bootstrap(access)
    original=client.get('/api/v1/preferencias').json()
    assert client.put('/api/v1/preferencias',headers=HEADERS,json={
        key:original[key] for key in ['modo_preferencia','desconto_maximo','minimo_escolhas','periodo_ocorrencias_dias']
    }).status_code==200
    other=secrets.token_urlsafe(24)
    assert client.post('/api/v1/auth/usuarios',headers=HEADERS,json={
        'username':'preferences-reader','name':'Preferences reader','password':other,'role':'operador'
    }).status_code==201
    sign_in(client,'preferences-reader',other)
    assert client.get('/preferencias.html').status_code==200
    legacy=client.get('/contas.html',follow_redirects=False)
    assert legacy.status_code==303 and legacy.headers['location']=='/preferencias.html#minha-conta'
    assert client.get('/api/v1/preferencias').json()==original
    assert client.put('/api/v1/preferencias',headers=HEADERS,json={
        'modo_preferencia':'desligado','desconto_maximo':0,'minimo_escolhas':3,'periodo_ocorrencias_dias':1
    }).status_code==403
    assert client.get('/api/v1/preferencias').json()==original
    assert client.get('/api/v1/auth/usuarios').status_code==403


def test_display_preferences_are_personal_and_opt_out_erases_remembered_filters(access):
    client,conn,code,password=access
    path='/api/v1/auth/exibicao'
    assert client.get(path).status_code==401
    client,conn,password=bootstrap(access)
    shared=client.get('/api/v1/preferencias').json()
    defaults=client.get(path).json()
    assert defaults=={'density':'comfortable','page_size':25,'remember_filters':False,'time_zone':'local','motion':'system','audit':{}}
    assert conn.execute('SELECT count(*) AS n FROM preferencias_exibicao').fetchone()['n']==0
    personal={key:value for key,value in defaults.items() if key!='audit'}
    personal.update(density='compact',page_size=10,remember_filters=True,time_zone='utc',motion='reduced')
    assert client.put(path,headers=HEADERS,json=personal).status_code==200
    state={'start':'2026-10-01','end':'2026-10-22','host':'<host> %_','q':'literal output','ordenar':'id','direcao':'asc'}
    assert client.put(path+'/auditoria',headers=HEADERS,json=state).json()=={'saved':True}
    stored=client.get(path).json()
    assert stored['audit']['host']==state['host'] and stored['audit']['start']==state['start']
    other=secrets.token_urlsafe(24)
    assert client.post('/api/v1/auth/usuarios',headers=HEADERS,json={
        'username':'display-reader','name':'Display reader','password':other,'role':'operador'}).status_code==201
    sign_in(client,'display-reader',other)
    assert client.get(path+'?usuario_id=1').json()==defaults
    assert client.put(path,headers=HEADERS,json={**personal,'density':'comfortable'}).status_code==200
    assert client.get(path).json()['density']=='comfortable'
    sign_in(client,'admin-test',password)
    assert client.get(path).json()==stored
    assert client.put(path,headers=HEADERS,json={**personal,'remember_filters':False}).json()['audit']=={}
    assert client.put(path+'/auditoria',headers=HEADERS,json=state).json()=={'saved':False}
    assert client.get(path).json()['audit']=={}
    assert client.get('/api/v1/preferencias').json()==shared
    assert conn.execute('SELECT count(*) AS n FROM audit_log').fetchone()['n']==0


def test_display_preferences_validate_scope_values_and_request_origin(access):
    client,conn,password=bootstrap(access)
    path='/api/v1/auth/exibicao'
    default=client.get(path).json()
    for body in [{'user_id':1},{'token':'do-not-echo-this'},{'density':'injected'},
                 {'page_size':1000000},{'time_zone':'Arbitrary/Zone'},{'audit':{'host':'arbitrary'}}]:
        response=client.put(path,headers=HEADERS,json=body)
        assert response.status_code==422
        assert 'do-not-echo-this' not in response.text
    for body in [{'ordenar':'id;DROP TABLE usuarios'},{'host':'x'*129},
                 {'start':'2026-10-22','end':'2026-01-01'},{'start':'2026-02-30','end':'2026-03-02'},
                 {'start':'2026-01-01'},{'start':'2020-01-01','end':'2026-01-01'}]:
        assert client.put(path+'/auditoria',headers=HEADERS,json=body).status_code==422
    assert client.put(path,headers={'Origin':'http://127.0.0.1'},json={}).status_code==403
    assert client.put(path,headers={**HEADERS,'Origin':'https://other.test'},json={}).status_code==403
    assert client.get(path).json()==default

def test_cookie_logout_hash_and_session_expiry(access):
    client,conn,password=bootstrap(access)
    raw=client.cookies.get(auth.COOKIE)
    assert conn.execute('SELECT token_hash FROM sessoes').fetchone()['token_hash']==auth.digest(raw)
    response=client.post('/api/v1/auth/entrar',headers=HEADERS,json={'username':'admin-test','password':password})
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    conn.execute("UPDATE sessoes SET ts_atividade=now()-interval '16 minutes'"); conn.commit()
    assert client.get('/api/v1/incidentes').status_code==401
    sign_in(client,'admin-test',password)
    client.post('/api/v1/auth/sair',headers=HEADERS)
    assert client.get('/api/v1/incidentes').status_code==401
    sign_in(client,'admin-test',password)
    conn.execute("UPDATE sessoes SET ts_expiracao=now()-interval '1 second'"); conn.commit()
    assert client.get('/api/v1/incidentes').status_code==401

def test_origin_transport_redaction_and_rate_limit(access):
    client,conn,password=bootstrap(access)
    assert client.post('/api/v1/auth/entrar',headers={**HEADERS,'Origin':'https://other.test'},json={'username':'admin-test','password':password}).status_code==403
    assert client.post('http://192.0.2.1/api/v1/auth/entrar',headers={**HEADERS,'Origin':'http://192.0.2.1'},json={'username':'admin-test','password':password}).status_code==403
    invalid=client.post('/api/v1/auth/entrar',headers=HEADERS,json={'username':'bad username','password':password})
    assert invalid.status_code==422 and password not in invalid.text
    conn.execute('UPDATE auth_limite SET tentativas=20'); conn.commit()
    assert client.post('/api/v1/auth/entrar',headers=HEADERS,json={'username':'admin-test','password':password}).status_code==429

def test_roles_account_disable_and_password_revocation(access):
    client,conn,password=bootstrap(access)
    uid=conn.execute("SELECT id FROM usuarios WHERE login='admin-test'").fetchone()['id']
    assert client.post(f'/api/v1/auth/usuarios/{uid}/desativar',headers=HEADERS).status_code==409
    other=secrets.token_urlsafe(24)
    assert client.post('/api/v1/auth/usuarios',headers=HEADERS,json={'username':'operator-test','name':'Operator','password':other,'role':'operador'}).status_code==201
    account=conn.execute("SELECT id FROM usuarios WHERE login='operator-test'").fetchone()['id']
    sign_in(client,'operator-test',other)
    for path in ['/api/v1/instalacao/configuracao','/api/v1/auth/usuarios']:
        assert client.get(path).status_code==403
    assert client.put('/api/v1/preferencias',headers=HEADERS,json={}).status_code==403
    assert client.get('/api/v1/incidentes').status_code==200
    sign_in(client,'admin-test',password)
    assert client.post(f'/api/v1/auth/usuarios/{account}/desativar',headers=HEADERS).status_code==200
    assert client.post('/api/v1/auth/entrar',headers=HEADERS,json={'username':'operator-test','password':other}).status_code==401
    changed=secrets.token_urlsafe(24)
    assert client.post('/api/v1/auth/senha',headers=HEADERS,json={'current_password':password,'new_password':changed}).status_code==200
    assert client.get('/api/v1/incidentes').status_code==401
    sign_in(client,'admin-test',changed)

@pytest.mark.parametrize('approved',[False,True])
def test_decision_uses_server_identity_and_science_does_not_approve(access,approved):
    client,conn,password=bootstrap(access)
    payload={'tipo_alerta':'service_down','hostname':'vm-alvo-01','severidade':'critica','metrica':'proc.num[nginx]','valor':0,'texto':'nginx: service nginx is not running. Active: inactive (dead)','id_evento':'auth-'+str(approved)}
    created=client.post('/debug/simulate-alert',headers=HEADERS,json=payload)
    assert created.status_code==201,created.text
    incident=created.json()['incidente_id']
    version=client.get('/api/v1/scripts-padrao').json()['versao']
    body={'aprovado':approved,'operador':'spoofed-identity','motivo':'Test rejection','versao_scripts':version}
    if approved:
        assert client.post(f'/api/v1/incidentes/{incident}/decisao',headers=HEADERS,json=body).status_code==409
    assert client.post('/api/v1/auth/ciencia',headers=HEADERS,json={'version':'0'*64}).status_code==409
    assert client.post('/api/v1/auth/ciencia',headers=HEADERS,json={'version':version}).status_code==200
    record=conn.execute('SELECT * FROM audit_log WHERE id=%s',(incident,)).fetchone()
    assert record['decisao_humana'] is None
    result=client.post(f'/api/v1/incidentes/{incident}/decisao',headers=HEADERS,json=body)
    assert result.status_code==202,result.text
    record=conn.execute('SELECT * FROM audit_log WHERE id=%s',(incident,)).fetchone()
    assert record['operador']=='admin-test'
    assert record['decisao_humana'] is approved
