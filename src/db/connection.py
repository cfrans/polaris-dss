"""Conexão com o banco de auditoria.

Sem ORM, por decisão: o SQL fica explícito e legível, o que importa num trabalho em que o esquema e
as consultas de KPI são objeto de apresentação e não apenas detalhe de implementação.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from ..engine.config import get_settings


# Banco indisponível deve falhar rápido: o padrão do libpq fica dezenas de segundos tentando, o que
# trava a suíte de testes em máquina sem Docker e mascara o erro real em produção.
TIMEOUT_CONEXAO_S = 5


@contextmanager
def conectar(
    dsn: str | None = None, autocommit: bool = False, connect_timeout: int = TIMEOUT_CONEXAO_S
) -> Iterator[psycopg.Connection]:
    """Abre conexão com linhas como dicionário.

    Por padrão sem autocommit: a gravação da decisão humana precisa de controle explícito de
    transação, já que a ordem entre persistir e executar é o que sustenta a invariante do trabalho.
    """
    conexao = psycopg.connect(
        dsn or get_settings().database_url,
        row_factory=dict_row,
        autocommit=autocommit,
        connect_timeout=connect_timeout,
    )
    try:
        yield conexao
    finally:
        conexao.close()
