"""Serve the installed public onboarding artifacts through a fixed allowlist."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = {
    "guia": ("docs/installation.md", "text/markdown", "polaris-installation.md"),
    "configuracao": (".env.example", "text/plain", "polaris.env.example"),
    "template": ("infra/zabbix/polaris-template-linux.yaml", "application/yaml", None),
    "media-type": ("infra/zabbix/polaris-mediatype.yaml", "application/yaml", None),
}
router = APIRouter()


@router.get("/api/v1/instalacao/arquivos/{artifact_id}", tags=["instalação"])
def download_artifact(artifact_id: str):
    artifact = ARTIFACTS.get(artifact_id)
    if artifact is None:
        raise HTTPException(404, "Arquivo de instalação não encontrado.")
    relative_path, media_type, filename = artifact
    path = ROOT / relative_path
    if not path.is_file():
        raise HTTPException(404, "Arquivo ausente nesta instalação. Consulte o repositório da versão.")
    return FileResponse(path, media_type=media_type, filename=filename or path.name,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
