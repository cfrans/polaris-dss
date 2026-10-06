"""Export experiment rounds, including discarded and unfinished rounds, to CSV.

Run from the repository root: python -m experiment.analysis.consolidar --output experiment/analysis/rounds.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.db.connection import conectar

ROOT = Path(__file__).resolve().parents[2]
COLUMNS = (
    "id", "cenario", "braco", "rodada", "descartada", "motivo_descarte",
    "versao_sistema", "commit_sha", "versao_kb", "host_alvo", "operador",
    "ts_injecao", "ts_verificado_ok", "passos_manuais", "comandos_usados",
    "resolvido", "observacoes",
)


def read_rounds(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT " + ", ".join(COLUMNS) + " FROM experiment_run ORDER BY id")
        return cursor.fetchall()


def csv_row(row: dict) -> dict:
    exported = {column: row[column] for column in COLUMNS}
    start, end = row["ts_injecao"], row["ts_verificado_ok"]
    for timestamp in (start, end):
        if timestamp is not None and (not isinstance(timestamp, datetime) or timestamp.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
    if start is None:
        raise ValueError("injection timestamp is missing")
    if end is not None and end < start:
        raise ValueError("recovery timestamp precedes injection")
    exported["mttr_segundos"] = (end - start).total_seconds() if end is not None else None
    for column in ("ts_injecao", "ts_verificado_ok"):
        timestamp = exported[column]
        if timestamp is not None:
            exported[column] = timestamp.astimezone(timezone.utc).isoformat()
    return exported


def export_csv(rows, output: Path) -> int:
    # Validate the complete snapshot before creating the output file.
    exported = [csv_row(row) for row in rows]
    with output.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(*COLUMNS, "mttr_segundos"))
        writer.writeheader()
        writer.writerows(exported)
    return len(exported)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        with conectar() as connection:
            rows = read_rounds(connection)
        count = export_csv(rows, output)
    except Exception as exc:
        print(f"Export aborted ({type(exc).__name__}); existing files are never replaced.", file=sys.stderr)
        return 2
    print(f"Exported {count} round(s) to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
