"""Authenticated setup forms with expiring test receipts and encrypted persistence."""
from __future__ import annotations

import hashlib
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, IPvAnyAddress, SecretStr

from ..engine.config import get_environment_settings, get_settings
from ..engine.setup_connections import generate_key, inspect_host, test_ssh
from ..engine.setup_vault import operation_guard, VaultError
from ..engine.zabbix_client import ZabbixClient
from .setup_access import authorize, unlock, vault_for_request, COOKIE, LOCK, SESSIONS

router = APIRouter(prefix="/api/v1/instalacao", tags=["instalação"])


class UnlockInput(BaseModel):
    code: SecretStr


class ZabbixInput(BaseModel):
    source: str = Field(default="saved", pattern="^(saved|environment)$")
    url: str = Field(max_length=2048)
    mode: str = Field(pattern="^(token|password)$")
    username: str = Field(default="", max_length=128)
    token: SecretStr | None = None
    password: SecretStr | None = None
    webhook_token: SecretStr | None = None


class SSHInput(BaseModel):
    source: str = Field(default="saved", pattern="^(saved|environment)$")
    host: IPvAnyAddress
    user: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_][a-z0-9_-]*[$]?$")
    expected_fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    generated_key: bool = False


class HostInput(BaseModel):
    host: IPvAnyAddress


class SaveInput(BaseModel):
    receipt: str = Field(max_length=128)


class PollingInput(BaseModel):
    interval: int = Field(ge=0, le=3600)


def public_state(source="saved"):
    env = get_environment_settings()
    data = vault_for_request().read()
    settings = env if source == "environment" else get_settings()
    try:
        parsed = urlsplit(settings.zabbix_url)
        hostname = f"[{parsed.hostname}]" if parsed.hostname and ":" in parsed.hostname else parsed.hostname
        safe_url = f"{parsed.scheme}://{hostname}" + (f":{parsed.port}" if parsed.port else "") + parsed.path if hostname else ""
    except ValueError:
        safe_url = ""
    return {"revision": data.get("revision"), "zabbix": {
        "url": safe_url, "username": settings.zabbix_user,
        "mode": "token" if settings.zabbix_token else "password",
        "token_available": bool(settings.zabbix_token),
        "password_available": bool(settings.zabbix_password),
        "webhook_available": bool(settings.polaris_webhook_token)},
        "ssh": {"host": settings.target_ssh_host, "user": settings.target_ssh_user,
                "key_available": bool(data.get("ssh_private_key") or settings.target_ssh_key_path),
                "draft_key": bool(data.get("draft_ssh_private_key")),
                "public_key": data.get("draft_ssh_public_key", data.get("ssh_public_key", ""))},
        "polling_interval": settings.polaris_polling_segundos,
        "validated": {stage: value.get("at", 0) for stage, value in data.get("validation", {}).items()}}


@router.get("/acesso")
def access_status(request: Request):
    from .setup_access import secure_transport
    try:
        secure_transport(request)
        safe = True
    except HTTPException:
        safe = False
    try:
        authorize(request)
        authenticated = True
    except HTTPException:
        authenticated = False
    return {"authenticated": authenticated, "secure_transport": safe}


@router.post("/acesso")
def sign_in(request: Request, body: UnlockInput, response: Response):
    token = unlock(request, body.code.get_secret_value())
    response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == "https",
                        samesite="strict", max_age=3600, path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@router.post("/sair")
def sign_out(request: Request, response: Response, session=Depends(authorize)):
    from .auth_routes import sign_out as account_sign_out
    with LOCK:
        SESSIONS.pop(request.state.user['token_hash'], None)
    return account_sign_out(request, response)


@router.get("/configuracao")
def configuration(response: Response, source: str = "saved", session=Depends(authorize)):
    if source not in {"saved", "environment"}:
        raise HTTPException(422, "Origem de configuração inválida.")
    response.headers["Cache-Control"] = "no-store"
    return public_state(source)


def remember_proof(session, stage, candidate, revision):
    receipt = secrets.token_urlsafe(32)
    with LOCK:
        session["proofs"][stage] = {"id": receipt, "candidate": candidate,
                                   "expires": time.monotonic() + 300, "revision": revision}
    return {"receipt": receipt, "expires_in": 300}


@router.post("/zabbix/testar")
def check_zabbix(body: ZabbixInput, session=Depends(authorize)):
    with LOCK:
        session["proofs"].pop("zabbix", None)
    data = vault_for_request().read()
    base = get_environment_settings() if body.source == "environment" else get_settings()
    url = body.url.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError()
        if not parsed.path.endswith("/api_jsonrpc.php"):
            url += "/api_jsonrpc.php"
        def secret(value, fallback):
            return value.get_secret_value() if value is not None else fallback
        token = secret(body.token, base.zabbix_token) if body.mode == "token" else ""
        password = secret(body.password, base.zabbix_password) if body.mode == "password" else ""
        webhook = secret(body.webhook_token, base.polaris_webhook_token)
        if (not token and body.mode == "token") or (body.mode == "password" and not (body.username and password)) or len(webhook) < 24:
            raise ValueError()
        if max(map(len, (token, password, webhook))) > 8192:
            raise ValueError()
        client = ZabbixClient(url=url, usuario=body.username, senha=password, token=token, timeout=4)
        version = client.versao()
        if not version.startswith("7.0."):
            raise ValueError()
        client.check_access()
    except Exception:
        raise HTTPException(422, "Teste não aprovado. Confira URL, Zabbix 7.0, credenciais, permissões e token de recepção com ao menos 24 caracteres.") from None
    candidate = {"settings": {"zabbix_url": url, "zabbix_user": body.username,
                               "zabbix_password": password, "zabbix_token": token,
                               "polaris_webhook_token": webhook}}
    return {**remember_proof(session, "zabbix", candidate, data["revision"]),
            "message": "Consulta autenticada aceita. Você já pode salvar esta configuração."}


@router.post("/ssh/chave")
def create_ssh_key(session=Depends(authorize)):
    private, public = generate_key()
    vault_for_request().update(lambda data: data.update(draft_ssh_private_key=private,
                                                        draft_ssh_public_key=public))
    with LOCK:
        session["proofs"].pop("ssh", None)
    return {"public_key": public}


@router.post("/ssh/identidade")
def inspect_identity(body: HostInput, session=Depends(authorize)):
    try:
        _, observed = inspect_host(str(body.host))
    except Exception:
        raise HTTPException(422, "Não foi possível consultar a identidade SSH desse IP.") from None
    return {"observed_fingerprint": observed,
            "message": "Compare com a impressão digital lida diretamente no alvo antes de confiar."}


@router.post("/ssh/testar")
def check_ssh(body: SSHInput, session=Depends(authorize)):
    with LOCK:
        session["proofs"].pop("ssh", None)
    data = vault_for_request().read()
    host = str(body.host)
    try:
        key, observed = inspect_host(host)
        if not secrets.compare_digest(observed, body.expected_fingerprint):
            raise ValueError()
        trusted = f"{host} {key.get_name()} {key.get_base64()}"
        base = get_environment_settings() if body.source == "environment" else get_settings()
        private = data.get("draft_ssh_private_key", "") if body.generated_key else data.get("ssh_private_key", "") if body.source != "environment" else ""
        if body.generated_key and not private:
            raise ValueError()
        test_ssh(host, body.user, private, trusted, base.target_ssh_key_path)
    except Exception:
        raise HTTPException(422, "Teste SSH não aprovado. Confira o IP, usuário, chave pública autorizada e a impressão digital confirmada no alvo.") from None
    candidate = {"settings": {"target_ssh_host": host, "target_ssh_user": body.user,
                               "target_ssh_key_path": "@cofre" if private else base.target_ssh_key_path},
                 "ssh_private_key": private, "ssh_known_hosts": trusted,
                 "ssh_public_key": data.get("draft_ssh_public_key", data.get("ssh_public_key", "")) if private else ""}
    return {**remember_proof(session, "ssh", candidate, data["revision"]),
            "message": "Identidade confirmada e conexão autenticada aceita. O teste executou apenas true."}


def ensure_idle():
    from ..db.connection import conectar
    try:
        with conectar(connect_timeout=3) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM audit_log WHERE status_execucao IN ('pendente','executando') LIMIT 1")
                if cursor.fetchone():
                    raise HTTPException(409, "Conclua os atendimentos pendentes antes de alterar as conexões.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Banco indisponível. Não foi possível confirmar que a alteração é segura.") from None


@router.post("/{stage}/salvar")
def save_configuration(stage: str, body: SaveInput, session=Depends(authorize)):
    if stage not in {"zabbix", "ssh"}:
        raise HTTPException(404, "Etapa inválida.")
    vault = vault_for_request()
    with LOCK:
        proof = session["proofs"].pop(stage, None)
    if not proof or not secrets.compare_digest(body.receipt, proof["id"]) or time.monotonic() > proof["expires"]:
        raise HTTPException(409, "Teste ausente ou vencido. Teste a configuração novamente.")
    try:
        with operation_guard(vault, exclusive=True):
            ensure_idle()
            def change(data):
                data["settings"].update(proof["candidate"]["settings"])
                for key, value in proof["candidate"].items():
                    if key != "settings":
                        data[key] = value
                data.setdefault("validation", {})[stage] = {"at": time.time()}
                if stage == "ssh":
                    data.pop("draft_ssh_private_key", None)
                    data.pop("draft_ssh_public_key", None)
            vault.update(change, revision=proof["revision"])
    except VaultError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"saved": True, "message": "Configuração testada salva com cifra no servidor."}


@router.post("/reconciliacao")
def configure_polling(body: PollingInput, session=Depends(authorize)):
    if 0 < body.interval < 5:
        raise HTTPException(422, "Use zero para pausar ou um intervalo entre 5 e 3600 segundos.")
    vault = vault_for_request()
    try:
        with operation_guard(vault, exclusive=True):
            ensure_idle()
            data = vault.read()
            if not data.get("validation", {}).get("zabbix"):
                raise HTTPException(409, "Teste e salve o Zabbix antes de ativar a reconciliação.")
            vault.update(lambda saved: saved["settings"].update(polaris_polling_segundos=body.interval),
                         revision=data["revision"])
    except VaultError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"saved": True, "message": "Intervalo salvo. O processo de reconciliação aplica a alteração no próximo ciclo."}
