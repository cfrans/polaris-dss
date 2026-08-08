import json
from pathlib import Path

import pytest

from src.engine.confidence import load_config
from src.engine.knowledge_base import load
from src.engine.models import Alert

FIXTURES = Path(__file__).parent / "fixtures"


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
