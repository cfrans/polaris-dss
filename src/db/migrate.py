"""Aplicação versionada de migrações do esquema.

Motivação: `CREATE TABLE IF NOT EXISTS` cria a tabela quando ela não existe, mas **não altera** uma
tabela existente. Reaplicar um arquivo de esquema num banco já criado roda sem erro e não faz nada,
o que dá falsa sensação de que a mudança foi aplicada. Some-se a isso que o
`docker-entrypoint-initdb.d` do PostgreSQL só executa na primeira criação do volume.

Cada migração é um arquivo `NNN_descricao.sql` aplicado uma única vez, dentro de uma transação, e
registrado em `schema_migrations` com o seu checksum. Migração já aplicada cujo arquivo tenha sido
editado depois faz a execução abortar: o esquema que gerou os dados de um experimento precisa ser
exatamente reconstruível, e edição silenciosa de migração aplicada destrói essa garantia.

    python -m src.db.migrate            aplica as pendentes
    python -m src.db.migrate --status   lista o estado de cada migração
    python -m src.db.migrate --dry-run  mostra o que seria aplicado, sem aplicar
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from ..engine.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
PADRAO_NOME = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")

TABELA_CONTROLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    versao      VARCHAR(8) PRIMARY KEY,
    nome        TEXT NOT NULL,
    checksum    CHAR(64) NOT NULL,
    aplicada_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE schema_migrations IS
    'Controle de versão do esquema. Não editar manualmente: o checksum garante que o banco
     corresponde exatamente aos arquivos de migração versionados em git.';
"""


class MigrationError(Exception):
    """Arquivo de migração fora do padrão, ausente, ou alterado após ter sido aplicado."""


@dataclass(frozen=True, slots=True)
class Migracao:
    versao: str
    nome: str
    caminho: Path

    @property
    def sql(self) -> str:
        return self.caminho.read_text(encoding="utf-8")

    @property
    def checksum(self) -> str:
        # Normaliza a quebra de linha: o projeto roda em Windows e macOS, e CRLF versus LF não
        # pode ser motivo para uma migração aplicada parecer alterada.
        conteudo = self.sql.replace("\r\n", "\n").encode("utf-8")
        return hashlib.sha256(conteudo).hexdigest()


def descobrir(diretorio: Path | None = None) -> list[Migracao]:
    diretorio = diretorio or MIGRATIONS_DIR
    if not diretorio.is_dir():
        raise MigrationError(f"diretório de migrações não encontrado: {diretorio}")

    encontradas: list[Migracao] = []
    for caminho in sorted(diretorio.glob("*.sql")):
        achado = PADRAO_NOME.match(caminho.name)
        if not achado:
            raise MigrationError(
                f"'{caminho.name}' fora do padrão NNN_descricao.sql "
                f"(três dígitos, minúsculas e sublinhado)"
            )
        encontradas.append(
            Migracao(versao=achado.group(1), nome=achado.group(2), caminho=caminho)
        )

    versoes = [m.versao for m in encontradas]
    duplicadas = {v for v in versoes if versoes.count(v) > 1}
    if duplicadas:
        raise MigrationError(f"número de migração duplicado: {sorted(duplicadas)}")
    return encontradas


def aplicadas(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT versao, checksum FROM schema_migrations")
        return dict(cur.fetchall())


def verificar_integridade(migracoes: list[Migracao], registradas: dict[str, str]) -> None:
    for m in migracoes:
        registrado = registradas.get(m.versao)
        if registrado and registrado != m.checksum:
            raise MigrationError(
                f"a migração {m.versao}_{m.nome} foi alterada depois de aplicada.\n"
                f"  checksum no banco:   {registrado}\n"
                f"  checksum do arquivo: {m.checksum}\n"
                f"Reverta a edição e crie uma migração nova com o ajuste. Alterar migração já "
                f"aplicada impede reconstruir o esquema que gerou os dados já coletados."
            )
    orfas = set(registradas) - {m.versao for m in migracoes}
    if orfas:
        raise MigrationError(
            f"o banco registra migrações que não existem em disco: {sorted(orfas)}. "
            f"O banco está à frente do repositório."
        )


def aplicar(conn, migracao: Migracao) -> None:
    """Uma transação por migração: ou o arquivo inteiro entra, ou nada dele entra."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(migracao.sql)
            cur.execute(
                "INSERT INTO schema_migrations (versao, nome, checksum) VALUES (%s, %s, %s)",
                (migracao.versao, migracao.nome, migracao.checksum),
            )


def executar(dsn: str | None = None, dry_run: bool = False, status: bool = False) -> int:
    settings = get_settings()
    migracoes = descobrir()

    with psycopg.connect(dsn or settings.database_url, autocommit=True, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(TABELA_CONTROLE)
        registradas = aplicadas(conn)
        verificar_integridade(migracoes, registradas)

        pendentes = [m for m in migracoes if m.versao not in registradas]

        if status:
            print(f"banco: {settings.db_name_audit} em {settings.db_host}:{settings.db_port}\n")
            for m in migracoes:
                marca = "aplicada" if m.versao in registradas else "PENDENTE"
                print(f"  [{marca:>8}] {m.versao}_{m.nome}")
            print(f"\n{len(registradas)} aplicada(s), {len(pendentes)} pendente(s)")
            return 0

        if not pendentes:
            print("esquema já está atualizado; nenhuma migração pendente")
            return 0

        for m in pendentes:
            if dry_run:
                print(f"[dry-run] aplicaria {m.versao}_{m.nome}")
                continue
            print(f"aplicando {m.versao}_{m.nome} ...", end=" ", flush=True)
            aplicar(conn, m)
            print("ok")

        if not dry_run:
            print(f"\n{len(pendentes)} migração(ões) aplicada(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="polaris-migrate", description="Aplica as migrações pendentes do esquema."
    )
    parser.add_argument("--status", action="store_true", help="lista o estado de cada migração")
    parser.add_argument("--dry-run", action="store_true", help="mostra o que seria aplicado")
    parser.add_argument("--dsn", default=None, help="DSN alternativo (padrão: vem do .env)")
    args = parser.parse_args(argv)

    try:
        return executar(dsn=args.dsn, dry_run=args.dry_run, status=args.status)
    except MigrationError as exc:
        print(f"erro de migração: {exc}", file=sys.stderr)
        return 2
    except psycopg.OperationalError as exc:
        print(f"não foi possível conectar ao banco: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
