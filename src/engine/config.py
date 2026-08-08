"""Configuração por variável de ambiente.

Todos os campos têm valor padrão e a instância é criada sob demanda: importar este módulo nunca
pode falhar por falta de `.env`, senão os testes do motor passam a depender de configuração.

Caminhos são resolvidos a partir da localização deste arquivo, e não do diretório de trabalho —
o projeto roda em três máquinas diferentes e é invocado de lugares diferentes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    zabbix_url: str = ""
    zabbix_user: str = ""
    zabbix_password: str = ""

    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name_audit: str = "polaris_audit"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    polaris_webhook_token: str = ""
    polaris_debug: bool = False
    polaris_confidence_history: bool = True

    target_ssh_host: str = ""
    target_ssh_user: str = "polaris"
    target_ssh_key_path: str = ""

    rules_path: Path = ROOT / "src" / "knowledge_base" / "rules.json"
    schema_path: Path = ROOT / "src" / "knowledge_base" / "schema.json"
    confidence_config_path: Path = ROOT / "src" / "knowledge_base" / "confidence_config.json"
    scripts_path: Path = ROOT / "src" / "scripts"

    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name_audit}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
