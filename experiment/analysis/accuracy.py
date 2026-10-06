"""Export human-assessed HITL accuracy by scenario, preserving failed attempts."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys

from experiment.analysis.consolidar import ROOT, read_rounds
from experiment.rounds import EXPECTED_RULES
from src.db.connection import conectar

COLUMNS = ('cenario', 'tentativas', 'sucessos', 'taxa_acerto_pct')


def calculate_accuracy(rows) -> list[dict]:
    counts = {}
    for row in rows:
        if (row['cenario'] not in EXPECTED_RULES or row['braco'] not in {'baseline', 'hitl'}
                or type(row['descartada']) is not bool
                or (row['resolvido'] is not None and type(row['resolvido']) is not bool)):
            raise ValueError('invalid round classification')
        if row['braco'] != 'hitl' or row['descartada'] or row['resolvido'] is None:
            continue
        attempted, succeeded = counts.get(row['cenario'], (0, 0))
        counts[row['cenario']] = attempted + 1, succeeded + int(row['resolvido'])
    return [dict(cenario=scenario, tentativas=attempted, sucessos=succeeded,
                 taxa_acerto_pct=(Decimal(succeeded * 100) / attempted).quantize(
                     Decimal('0.1'), rounding=ROUND_HALF_UP))
            for scenario, (attempted, succeeded) in sorted(counts.items())]


def export_accuracy(rows, output: Path) -> int:
    classified = calculate_accuracy(rows)
    with output.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(classified)
    return len(classified)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        with conectar() as connection:
            rows = read_rounds(connection)
        count = export_accuracy(rows, output)
    except Exception as exc:
        print(f'Accuracy export aborted ({type(exc).__name__}).', file=sys.stderr)
        return 2
    print(f'Exported {count} assessed scenario(s) to {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
