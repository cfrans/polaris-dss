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
    from .auth import require_admin
    user = require_admin(request)
    key = user['token_hash']
    with LOCK:
        now = time.monotonic()
        for expired in [k for k,v in SESSIONS.items() if now-v['last']>900]:
            del SESSIONS[expired]
        if key not in SESSIONS:
            if len(SESSIONS)>=128:
                raise HTTPException(429, 'Muitas sessões de configuração ativas.')
            SESSIONS[key] = {'proofs': {}, 'last': now}
        SESSIONS[key]['last'] = now
        return SESSIONS[key]


def unlock(request, code):
    raise HTTPException(410, 'Use o login individual. O código serve apenas para criar o primeiro administrador.')
