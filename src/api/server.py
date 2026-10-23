"""Aplicação FastAPI do Polaris DSS.

Serve a API e a interface Human-in-the-Loop no mesmo processo — a interface é estática, sem etapa
de build, e não justifica um servidor separado.

    uvicorn src.api.server:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
import psycopg
from . import auth
from .auth_routes import router as auth_router
from .display_preferences import router as display_router
from .audit_routes import router as audit_router

from ..engine.config import get_settings
from ..engine.confidence import load_config
from ..engine.knowledge_base import KnowledgeBaseError, load
from .routes import VERSAO_API, router
from .installation import router as installation_router
from .setup_configuration import router as setup_router
from .setup_access import authorize, check_origin
from ..engine.setup_vault import configured_vault, operation_guard, VaultError

WEB = Path(__file__).resolve().parents[1] / "web"


class FreshStaticFiles(StaticFiles):
    """Avoid mixing an updated page with JavaScript cached from an older release."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response

DESCRICAO = """
Sistema Especialista de Suporte à Decisão para remediação de incidentes de infraestrutura.

O motor calcula um índice de confiança e **para**. Nenhuma remediação é executada sem uma
aprovação humana previamente registrada no banco de auditoria — a verificação é feita relendo o
registro persistido, e não confiando em quem chamou.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A base de conhecimento é carregada uma vez e mantida em memória. Base inválida derruba a
    # inicialização: subir com cobertura menor que a declarada seria pior que não subir.
    app.state.settings = get_settings()
    app.state.config = load_config()
    try:
        app.state.kb = load()
    except KnowledgeBaseError as exc:
        raise RuntimeError(f"base de conhecimento inválida: {exc}") from exc
    yield


app = FastAPI(
    title="Polaris DSS",
    description=DESCRICAO,
    version=VERSAO_API,
    lifespan=lifespan,
    docs_url="/docs",
)


@app.middleware("http")
async def configuration_boundary(request: Request, call_next):
    from ..engine.config import get_environment_settings
    path = request.url.path
    try:
        if path in {'/','/index.html','/configuracao.html','/contas.html','/preferencias.html','/laboratorio.html','/auditoria.html'}:
            try:
                request.state.user = await run_in_threadpool(auth.authenticate, request)
            except HTTPException as exc:
                if exc.status_code == 401:
                    return RedirectResponse('/login.html?next='+path, status_code=303, headers={'Cache-Control':'no-store'})
                raise
            if path == '/configuracao.html':
                auth.require_admin(request)
            if path == '/contas.html':
                return RedirectResponse('/preferencias.html#minha-conta', status_code=303, headers={'Cache-Control':'no-store'})
        auth_path = path.startswith('/api/v1/auth/')
        artifacts = path.startswith('/api/v1/instalacao/arquivos/') and request.method in {'GET','HEAD'}
        if auth_path and request.method not in {'GET','HEAD'}:
            auth.secure_transport(request)
            check_origin(request)
            if request.headers.get('x-polaris-auth') != '1':
                raise HTTPException(403, 'Cabeçalho de proteção ausente.')
            try:
                length = int(request.headers.get('content-length','0'))
            except ValueError:
                raise HTTPException(400, 'Tamanho de solicitação inválido.') from None
            if length < 0 or length > 65536:
                raise HTTPException(413, 'Solicitação excede o tamanho permitido.')
        if not auth_path and not artifacts and (path.startswith('/api/') or path.startswith('/debug/')):
            request.state.user = await run_in_threadpool(auth.authenticate, request)
            if path.startswith('/api/v1/instalacao/') or path.startswith('/debug/') or (
                request.method not in {'GET','HEAD'} and path in {'/api/v1/preferencias','/api/v1/regras/reload'}):
                auth.require_admin(request)
        vault = configured_vault(get_environment_settings())
        if path.startswith("/api/v1/instalacao/"):
            if request.method not in {"GET", "HEAD"}:
                check_origin(request)
                if request.headers.get("x-polaris-setup") != "1":
                    raise HTTPException(403, "Cabeçalho de proteção ausente.")
                try:
                    length = int(request.headers.get("content-length", "0"))
                except ValueError:
                    raise HTTPException(400, "Tamanho de solicitação inválido.") from None
                if length < 0 or length > 65536:
                    raise HTTPException(413, "Solicitação excede o tamanho permitido.")
            response = await call_next(request)
        else:
            with operation_guard(vault):
                request.app.state.settings = get_settings()
                response = await call_next(request)
        if path.startswith('/api/'):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"mensagem": str(exc.detail)}, headers={"Cache-Control":"no-store"})
    except VaultError as exc:
        return JSONResponse(status_code=503, content={"mensagem": str(exc)})
    except psycopg.Error:
        return JSONResponse(status_code=503, content={'mensagem':'Banco de acesso indisponível. Confira o serviço e as migrações.'})


@app.exception_handler(RequestValidationError)
async def redact_setup_validation(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(("/api/v1/instalacao/", '/api/v1/auth/')):
        return JSONResponse(status_code=422, content={"mensagem": "Confira os campos obrigatórios e seus formatos."})
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(HTTPException)
async def erro_http(request: Request, exc: HTTPException) -> JSONResponse:
    """Formato único de erro, com mensagem legível em português — ela aparece na interface."""
    if isinstance(exc.detail, dict) and "erro" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"erro": "erro", "mensagem": str(exc.detail), "detalhes": {}},
    )


app.include_router(router)
app.include_router(installation_router)
app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(display_router)
app.include_router(audit_router)

# Montado por último: uma montagem em "/" captura tudo o que não casou com as rotas acima.
app.mount("/", FreshStaticFiles(directory=WEB, html=True), name="web")
