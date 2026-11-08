"""Read-only facts about this installation: version, knowledge base and release notes."""
from __future__ import annotations

import re
from functools import lru_cache

from fastapi import APIRouter, Request, Response

from . import auth
from ..engine.config import ROOT
from ..engine.knowledge_base import load

router = APIRouter(prefix="/api/v1", tags=["sobre"])
REPOSITORY = "https://github.com/cfrans/polaris-dss"
CHANGELOG = ROOT / "CHANGELOG.md"


@lru_cache(maxsize=4)
def release_notes(version: str) -> dict:
    """Section of CHANGELOG.md for this version; development builds read the unreleased section."""
    try:
        text = CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return {"title": "", "groups": []}
    heading = "[Não lançado]" if version.endswith("-dev") else f"[{version}]"
    sections = re.split(r"(?m)^## ", text)
    section = next((part for part in sections if part.startswith(heading)), "")
    if not section:
        return {"title": "", "groups": []}
    title, _, body = section.partition("\n")
    groups = []
    for block in re.split(r"(?m)^### ", body)[1:]:
        name, _, content = block.partition("\n")
        items = []
        for line in content.splitlines():
            if line.startswith("- "):
                items.append(line[2:].strip())
            elif line.startswith("  ") and items and line.strip():
                items[-1] += " " + line.strip()
        if items:
            groups.append({"name": name.strip(), "items": items})
    return {"title": title.strip(), "groups": groups}


@router.get("/sobre")
def about(request: Request, response: Response):
    from .routes import VERSAO_API
    auth.authenticate(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        kb_version = load().versao_kb
    except Exception:
        kb_version = None
    return {"version": VERSAO_API, "knowledge_base": kb_version,
            "repository": REPOSITORY, "license": "MIT",
            "documentation": REPOSITORY + "/tree/main/docs",
            "changelog_url": REPOSITORY + "/blob/main/CHANGELOG.md",
            "experiment_version": "1.0.3-experimento",
            "notes": release_notes(VERSAO_API)}
