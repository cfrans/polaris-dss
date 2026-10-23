"""Individual identities and revocable opaque sessions persisted in PostgreSQL."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import os
import secrets

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from fastapi import HTTPException
from ..db.connection import conectar
from .setup_access import secure_transport, check_origin

COOKIE = "polaris_session"


def password_hash(password):
    if not 15 <= len(password) <= 128:
        raise HTTPException(422, "Use uma senha ou frase entre 15 e 128 caracteres.")
    return Argon2id(salt=os.urandom(16), length=32, iterations=2, lanes=1,
                    memory_cost=19456).derive_phc_encoded(password.encode())


def password_matches(password, encoded):
    try:
        Argon2id.verify_phc_encoded(password.encode(), encoded)
        return True
    except (InvalidKey, ValueError):
        return False


@lru_cache
def dummy_hash():
    return password_hash(secrets.token_urlsafe(32))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def rate_limit(conn):
    row = conn.execute("SELECT *, janela < now() - interval '1 minute' AS vencida FROM auth_limite WHERE id=1 FOR UPDATE").fetchone()
    if not row or (not row['vencida'] and row['tentativas'] >= 20):
        raise HTTPException(429, "Muitas tentativas. Aguarde um minuto.")
    conn.execute("UPDATE auth_limite SET tentativas=CASE WHEN %s THEN 1 ELSE tentativas+1 END, janela=CASE WHEN %s THEN now() ELSE janela END WHERE id=1", (row['vencida'], row['vencida']))
    conn.commit()


def authenticate(request):
    secure_transport(request)
    if request.method not in {"GET", "HEAD"}:
        check_origin(request)
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "Entre na sua conta para continuar.")
    key = digest(token)
    with conectar() as conn:
        row = conn.execute("""UPDATE sessoes s SET ts_atividade=now() FROM usuarios u
            WHERE s.token_hash=%s AND s.usuario_id=u.id AND u.ativo
            AND s.ts_expiracao>now() AND s.ts_atividade>now()-interval '15 minutes'
            RETURNING u.id,u.login,u.nome,u.perfil,s.token_hash""", (key,)).fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(401, "Sua sessão terminou. Entre novamente.")
    return dict(row)


def require_admin(request):
    user = request.state.user
    if user['perfil'] != 'admin':
        raise HTTPException(403, "Esta área requer uma conta administradora.")
    return user


def login(request, username, password):
    secure_transport(request)
    check_origin(request)
    with conectar() as conn:
        rate_limit(conn)
        user = conn.execute("SELECT * FROM usuarios WHERE login=%s", (username,)).fetchone()
        valid = password_matches(password, user['senha_hash'] if user else dummy_hash())
        if not valid or not user or not user['ativo']:
            raise HTTPException(401, "Usuário ou senha inválidos.")
        # Serialize issuance against disabling/resetting the same account.
        current = conn.execute("SELECT * FROM usuarios WHERE id=%s FOR UPDATE", (user['id'],)).fetchone()
        if not current['ativo'] or current['senha_hash'] != user['senha_hash']:
            raise HTTPException(401, "Usuário ou senha inválidos.")
        conn.execute("DELETE FROM sessoes WHERE ts_expiracao<now() OR ts_atividade<now()-interval '15 minutes'")
        count = conn.execute("SELECT count(*) AS n FROM sessoes WHERE usuario_id=%s", (user['id'],)).fetchone()['n']
        if count >= 5:
            conn.execute("DELETE FROM sessoes WHERE token_hash=(SELECT token_hash FROM sessoes WHERE usuario_id=%s ORDER BY ts_criacao LIMIT 1)", (user['id'],))
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO sessoes(token_hash,usuario_id,ts_expiracao) VALUES(%s,%s,now()+interval '8 hours')", (digest(token), user['id']))
        conn.commit()
    return token


def acknowledged(user, version):
    with conectar() as conn:
        return conn.execute("SELECT 1 FROM ciencia_scripts WHERE usuario_id=%s AND versao=%s", (user['id'], version)).fetchone() is not None


def authorize_decision(conn, user):
    row = conn.execute("""SELECT u.id FROM usuarios u JOIN sessoes s ON s.usuario_id=u.id
        WHERE u.id=%s AND u.ativo AND s.token_hash=%s AND s.ts_expiracao>now()
        AND s.ts_atividade>now()-interval '15 minutes' FOR SHARE OF u,s""",
        (user['id'], user['token_hash'])).fetchone()
    if row is None:
        raise HTTPException(401, 'Sua sessão terminou. Entre novamente antes de decidir.')


def main():
    """Local administrator recovery; passwords never travel through command arguments."""
    import argparse
    import getpass
    parser = argparse.ArgumentParser(description='Recupera uma senha com acesso local ao servidor.')
    parser.add_argument('--reset-password', required=True, metavar='LOGIN')
    args = parser.parse_args()
    password = getpass.getpass('Nova frase-senha: ')
    if password != getpass.getpass('Confirme a frase-senha: '):
        raise SystemExit('As senhas não coincidem.')
    encoded = password_hash(password)
    with conectar() as conn:
        row = conn.execute('UPDATE usuarios SET senha_hash=%s WHERE login=%s RETURNING id', (encoded,args.reset_password)).fetchone()
        if row is None:
            raise SystemExit('Conta não encontrada.')
        conn.execute('DELETE FROM sessoes WHERE usuario_id=%s', (row['id'],))
        conn.commit()
    print('Senha atualizada e sessões encerradas. O perfil e o estado da conta foram preservados.')


if __name__ == '__main__':
    main()
