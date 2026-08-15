"""Aplicação FastAPI do Polaris DSS.

Serve a API e a interface Human-in-the-Loop no mesmo processo — a interface é estática, sem etapa
de build, e não justifica um servidor separado.

    uvicorn src.api.server:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..engine.config import get_settings
from ..engine.confidence import load_config
from ..engine.knowledge_base import KnowledgeBaseError, load
from .routes import VERSAO_API, router

WEB = Path(__file__).resolve().parents[1] / "web"

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

# Montado por último: uma montagem em "/" captura tudo o que não casou com as rotas acima.
app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
