"""Sobre o Polaris: versão e notas lidas do CHANGELOG, sem exigir rede nem banco."""
from __future__ import annotations

from src.api import about_routes


def test_release_notes_read_unreleased_section_for_development_builds(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Não lançado]\n\n### Adicionado\n- Página `Sobre` com\n  notas da versão.\n"
                         "- **Login** individual.\n\n### Corrigido\n- Etapa 6.\n\n## [1.0.3-experimento] — 2026-10-18\n\n"
                         "### Corrigido\n- Reconciliação.\n", encoding="utf-8")
    monkeypatch.setattr(about_routes, "CHANGELOG", changelog)
    about_routes.release_notes.cache_clear()
    notes = about_routes.release_notes("1.1.0-dev")
    assert notes["title"] == "[Não lançado]"
    assert notes["groups"][0] == {"name": "Adicionado", "items": ["Página `Sobre` com notas da versão.", "**Login** individual."]}
    assert notes["groups"][1]["items"] == ["Etapa 6."]
    assert about_routes.release_notes("1.0.3-experimento")["groups"] == [{"name": "Corrigido", "items": ["Reconciliação."]}]
    assert about_routes.release_notes("9.9.9")["groups"] == []
    about_routes.release_notes.cache_clear()


def test_release_notes_tolerate_missing_changelog(tmp_path, monkeypatch):
    monkeypatch.setattr(about_routes, "CHANGELOG", tmp_path / "ausente.md")
    about_routes.release_notes.cache_clear()
    assert about_routes.release_notes("1.1.0-dev") == {"title": "", "groups": []}
    about_routes.release_notes.cache_clear()


def test_real_changelog_has_notes_for_the_current_version():
    from src.api.routes import VERSAO_API
    about_routes.release_notes.cache_clear()
    assert about_routes.release_notes(VERSAO_API)["groups"], "CHANGELOG sem seção para a versão atual"


def test_about_reports_version_base_and_links(cliente):
    from src.api.routes import VERSAO_API
    data = cliente.get("/api/v1/sobre").json()
    assert data["version"] == VERSAO_API and data["license"] == "MIT"
    assert data["repository"].startswith("https://github.com/") and data["knowledge_base"]
    assert data["notes"]["groups"]
