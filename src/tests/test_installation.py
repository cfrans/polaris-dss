"""Public artifacts must work before the database is configured, without exposing files."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.server import app

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("artifact_id,relative_path,content_type", [
    ("guia", "docs/installation.md", "text/markdown"),
    ("configuracao", ".env.example", "text/plain"),
    ("template", "infra/zabbix/polaris-template-linux.yaml", "application/yaml"),
    ("media-type", "infra/zabbix/polaris-mediatype.yaml", "application/yaml"),
])
def test_download_is_exact_installed_public_file(artifact_id, relative_path, content_type, monkeypatch):
    def refuse_database(*args, **kwargs):
        pytest.fail("An artifact download must not open the database")
    monkeypatch.setattr("src.api.routes.conectar", refuse_database)
    with TestClient(app) as client:
        response = client.get(f"/api/v1/instalacao/arquivos/{artifact_id}")
    assert response.status_code == 200
    assert response.content == (ROOT / relative_path).read_bytes()
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("artifact_id", [".env", "secrets", "README.md", "unknown", "..%2F.env"])
def test_only_allowlisted_identifiers_are_downloadable(artifact_id):
    with TestClient(app) as client:
        assert client.get(f"/api/v1/instalacao/arquivos/{artifact_id}").status_code == 404


def test_missing_artifact_does_not_report_success(monkeypatch):
    monkeypatch.setattr("src.api.installation.ARTIFACTS", {"guia": ("absent-file.md", "text/plain", None)})
    with TestClient(app) as client:
        assert client.get("/api/v1/instalacao/arquivos/guia").status_code == 404
