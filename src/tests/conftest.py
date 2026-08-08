import json
from pathlib import Path

import pytest

from src.engine.confidence import load_config
from src.engine.knowledge_base import load
from src.engine.models import Alert

FIXTURES = Path(__file__).parent / "fixtures"

TABELAS_VOLATEIS = ("audit_log", "experiment_run")


@pytest.fixture(scope="session")
def kb():
    return load()


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture
def alerta():
    def _carregar(nome: str, **overrides) -> Alert:
        dados = json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
        dados.update(overrides)
        return Alert.from_dict(dados)

    return _carregar


@pytest.fixture(scope="session")
def _conexao():
    """Sonda o banco uma única vez por sessão.

    Uma tentativa por teste custaria o timeout de conexão vezes o número de testes de integração
    numa máquina sem Docker, o que faria a suíte parecer travada.
    """
    psycopg = pytest.importorskip("psycopg", reason="psycopg não instalado")
    from src.db.connection import conectar

    try:
        with conectar() as conexao:
            with conexao.cursor() as cur:
                cur.execute("SELECT 1 FROM audit_log LIMIT 1")
            conexao.rollback()
            yield conexao
    except psycopg.errors.UndefinedTable:
        yield pytest.skip.Exception("esquema não aplicado: rode `python -m src.db.migrate`")
    except psycopg.OperationalError as exc:
        yield pytest.skip.Exception(f"banco de auditoria indisponível: {exc}")


@pytest.fixture
def conn(_conexao):
    """Conexão com o banco limpo. Pula quando não há PostgreSQL disponível."""
    if isinstance(_conexao, BaseException):
        pytest.skip(str(_conexao))
    with _conexao.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABELAS_VOLATEIS)} RESTART IDENTITY CASCADE")
    _conexao.commit()
    return _conexao
