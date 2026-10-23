"""Short-lived administrative setup sessions; no operator identity is inferred."""
import hashlib
import secrets
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from ..engine.config import get_environment_settings
from ..engine.setup_vault import configured_vault

SESSIONS = {}
ATTEMPTS = deque()
LOCK = threading.RLock()
COOKIE = "polaris_setup"


def vault_for_request():
    vault = configured_vault(get_environment_settings())
    if vault is None:
        raise HTTPException(503, "Habilite os volumes do assistente no servidor.")
    return vault


def secure_transport(request: Request):
    if request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "Abra o assistente por HTTPS; HTTP é permitido apenas no endereço local.")


def check_origin(request: Request):
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("origin") != expected:
        raise HTTPException(403, "Origem da solicitação não autorizada.")


def authorize(request: Request):
    secure_transport(request)
    if request.method not in {"GET", "HEAD"}:
        check_origin(request)
    token = request.cookies.get(COOKIE, "")
    key = hashlib.sha256(token.encode()).hexdigest()
    data = vault_for_request().read()
    with LOCK:
        now = time.monotonic()
        session = SESSIONS.get(key)
        if not session or now > session["expires"] or now - session["last"] > 900 or session["access"] != data.get("access_hash"):
            SESSIONS.pop(key, None)
            raise HTTPException(401, "Desbloqueie o acesso administrativo ao assistente.")
        session["last"] = now
        return session


def unlock(request, code):
    secure_transport(request)
    check_origin(request)
    vault = vault_for_request()
    with LOCK:
        now = time.monotonic()
        while ATTEMPTS and ATTEMPTS[0] < now - 60:
            ATTEMPTS.popleft()
        if len(ATTEMPTS) >= 10:
            raise HTTPException(429, "Muitas tentativas. Aguarde um minuto.")
        ATTEMPTS.append(now)
        data = vault.read()
        if not data.get("access_hash") or not secrets.compare_digest(hashlib.sha256(code.encode()).hexdigest(), data["access_hash"]):
            raise HTTPException(401, "Código de acesso inválido ou acesso ainda não inicializado.")
        for key in list(SESSIONS):
            if SESSIONS[key]["expires"] < now or now - SESSIONS[key]["last"] > 900:
                del SESSIONS[key]
        if len(SESSIONS) >= 128:
            raise HTTPException(429, "Limite de sessões alcançado. Encerre uma sessão existente.")
        token = secrets.token_urlsafe(32)
        SESSIONS[hashlib.sha256(token.encode()).hexdigest()] = {
            "access": data["access_hash"], "expires": now + 3600, "last": now, "proofs": {}}
        return token
