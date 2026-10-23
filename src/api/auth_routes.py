"""Account bootstrap, login, account administration and script acknowledgement."""
import hashlib
import secrets
import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from ..db.connection import conectar
from ..engine.script_catalog import load_catalog
from . import auth
from .setup_access import vault_for_request

router = APIRouter(prefix='/api/v1/auth', tags=['acesso'])

class LoginInput(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r'^[a-z0-9][a-z0-9_.-]{2,63}$')
    password: SecretStr = Field(max_length=128)

class AccountInput(LoginInput):
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(default='operador', pattern='^(admin|operador)$')

class BootstrapInput(AccountInput):
    code: SecretStr = Field(max_length=128)

class PasswordInput(BaseModel):
    current_password: SecretStr = Field(max_length=128)
    new_password: SecretStr = Field(max_length=128)

class AcknowledgementInput(BaseModel):
    version: str = Field(pattern=r'^[a-f0-9]{64}$')


def public_user(user):
    return {k: user[k] for k in ('id','login','nome','perfil')}

@router.get('/sessao')
def session_status(request: Request):
    try:
        user = auth.authenticate(request)
        return {'authenticated': True, 'user': public_user(user)}
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    with conectar() as conn:
        exists = conn.execute('SELECT 1 FROM usuarios LIMIT 1').fetchone() is not None
    return {'authenticated': False, 'bootstrap_required': not exists}

@router.post('/bootstrap', status_code=201)
def bootstrap(body: BootstrapInput):
    with conectar() as conn:
        auth.rate_limit(conn)
        conn.execute('SELECT pg_advisory_xact_lock(914513)')
        if conn.execute('SELECT 1 FROM usuarios LIMIT 1').fetchone():
            raise HTTPException(409, 'O primeiro administrador já foi criado. Entre na sua conta.')
        data = vault_for_request().read()
        if not data.get('access_hash') or not secrets.compare_digest(hashlib.sha256(body.code.get_secret_value().encode()).hexdigest(), data['access_hash']):
            raise HTTPException(401, 'Código de instalação inválido.')
        encoded = auth.password_hash(body.password.get_secret_value())
        conn.execute("INSERT INTO usuarios(login,nome,senha_hash,perfil) VALUES(%s,%s,%s,'admin')", (body.username, body.name, encoded))
        conn.commit()
    return {'created': True}

@router.post('/entrar')
def sign_in(request: Request, body: LoginInput, response: Response):
    token = auth.login(request, body.username, body.password.get_secret_value())
    response.set_cookie(auth.COOKIE, token, httponly=True, secure=request.url.scheme=='https', samesite='strict', path='/', max_age=28800)
    return {'authenticated': True}

@router.post('/sair')
def sign_out(request: Request, response: Response):
    user = auth.authenticate(request)
    with conectar() as conn:
        conn.execute('DELETE FROM sessoes WHERE token_hash=%s', (user['token_hash'],))
        conn.commit()
    response.delete_cookie(auth.COOKIE, path='/')
    return {'authenticated': False}

@router.post('/senha')
def change_password(request: Request, body: PasswordInput, response: Response):
    user = auth.authenticate(request)
    encoded = auth.password_hash(body.new_password.get_secret_value())
    with conectar() as conn:
        auth.rate_limit(conn)
        row = conn.execute('SELECT * FROM usuarios WHERE id=%s FOR UPDATE', (user['id'],)).fetchone()
        if not row['ativo'] or not auth.password_matches(body.current_password.get_secret_value(), row['senha_hash']):
            raise HTTPException(401, 'Senha atual inválida.')
        conn.execute('UPDATE usuarios SET senha_hash=%s WHERE id=%s', (encoded, user['id']))
        conn.execute('DELETE FROM sessoes WHERE usuario_id=%s', (user['id'],))
        conn.commit()
    response.delete_cookie(auth.COOKIE, path='/')
    return {'message': 'Senha alterada. Entre novamente em sua conta.'}

@router.get('/usuarios')
def list_users(request: Request):
    request.state.user = auth.authenticate(request)
    auth.require_admin(request)
    with conectar() as conn:
        return {'users': conn.execute('SELECT id,login,nome,perfil,ativo FROM usuarios ORDER BY login').fetchall()}

@router.post('/usuarios', status_code=201)
def create_user(request: Request, body: AccountInput):
    request.state.user = auth.authenticate(request)
    auth.require_admin(request)
    encoded = auth.password_hash(body.password.get_secret_value())
    try:
        with conectar() as conn:
            conn.execute('INSERT INTO usuarios(login,nome,senha_hash,perfil) VALUES(%s,%s,%s,%s)', (body.username, body.name, encoded, body.role))
            conn.commit()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, 'Esse nome de usuário já está em uso.') from None
    return {'created': True}

@router.post('/usuarios/{user_id}/desativar')
def disable_user(user_id: int, request: Request):
    request.state.user = auth.authenticate(request)
    actor = auth.require_admin(request)
    if actor['id'] == user_id:
        raise HTTPException(409, 'Não é possível desativar sua própria conta.')
    with conectar() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(914514)')
        active = conn.execute('SELECT ativo FROM usuarios WHERE id=%s', (actor['id'],)).fetchone()
        if not active or not active['ativo']:
            raise HTTPException(401, 'Sua sessão terminou. Entre novamente.')
        row = conn.execute('UPDATE usuarios SET ativo=false WHERE id=%s RETURNING id', (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Conta não encontrada.')
        conn.execute('DELETE FROM sessoes WHERE usuario_id=%s', (user_id,))
        conn.commit()
    return {'disabled': True}

@router.get('/ciencia')
def acknowledgement(request: Request):
    user = auth.authenticate(request)
    version = load_catalog().sha256
    with conectar() as conn:
        record = conn.execute('SELECT ts_ciencia FROM ciencia_scripts WHERE usuario_id=%s AND versao=%s', (user['id'],version)).fetchone()
    return {'version': version, 'acknowledged': record is not None, 'at': record['ts_ciencia'] if record else None}

@router.post('/ciencia')
def acknowledge(request: Request, body: AcknowledgementInput):
    user = auth.authenticate(request)
    if body.version != load_catalog().sha256:
        raise HTTPException(409, 'Os scripts mudaram. Revise novamente.')
    with conectar() as conn:
        conn.execute('INSERT INTO ciencia_scripts(usuario_id,versao) VALUES(%s,%s) ON CONFLICT DO NOTHING', (user['id'], body.version))
        conn.commit()
    return {'acknowledged': True}
