"""Export reproducible KPI tables and figures from a CSV or a read-only DB snapshot."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

from experiment.analysis.consolidar import COLUMNS, ROOT, csv_row
from experiment.analysis.summary import AUDIT_COLUMNS, analyze, normalize_rows
from experiment.rounds import require_idle
from src.db.connection import conectar

SUMMARY_COLUMNS = ('cenario', 'braco', 'total', 'descartadas', 'nao_avaliadas', 'avaliadas', 'falhas',
                   'sem_t5', 'sem_passos', 'mttr_n', 'mttr_media_s', 'mttr_desvio_s', 'mttr_min_s', 'mttr_max_s',
                   'passos_n', 'passos_media', 'passos_desvio', 'passos_min', 'passos_max', 'decomposicao_incompleta')
COMPARISON_COLUMNS = ('cenario',) + tuple(f'{metric}_{key}' for metric in ('mttr', 'passos')
    for key in ('n_baseline', 'n_hitl', 'media_baseline', 'media_hitl', 'reducao_pct', 'pares',
                'sem_par_baseline', 'sem_par_hitl', 'pareado_media_baseline', 'pareado_media_hitl',
                'pareado_reducao_pct'))
PHASE_COLUMNS = ('cenario', 'n', 'mttr_media_s', 'deteccao_s', 'ingestao_s', 'processamento_exibicao_s',
                 'decisao_humana_s', 'execucao_recuperacao_s')
TABLES = {
    'summary': ('resumo.csv', SUMMARY_COLUMNS),
    'comparison': ('comparacao.csv', COMPARISON_COLUMNS),
    'accuracy': ('acerto.csv', ('cenario', 'tentativas', 'sucessos', 'taxa_acerto_pct')),
    'phases': ('decomposicao.csv', PHASE_COLUMNS),
}


def read_snapshot(connection):
    require_idle(connection)
    columns = ', '.join('r.' + c for c in COLUMNS)
    fields = ', '.join(f'CASE WHEN COUNT(*) = 1 THEN MIN({c}) END AS {c}'
                       for c in ('id_evento', 'regra_disparada', 'ts_deteccao', 'ts_criacao',
                                 'ts_exibicao', 'ts_aprovacao'))
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute(f'SELECT {columns}, a.* FROM experiment_run r LEFT JOIN LATERAL '
                           f'(SELECT COUNT(*) AS audit_count, '
                           f'CASE WHEN COUNT(*) = 1 THEN MIN(id) END AS incident_id, {fields} '
                           'FROM audit_log WHERE experiment_run_id = r.id) a ON TRUE ORDER BY r.id')
            return cursor.fetchall()


def write_csv(path, rows, columns, kind):
    with path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=(*columns, 'tipo_dados'))
        writer.writeheader()
        for row in rows:
            writer.writerow({**{c: row.get(c) for c in columns}, 'tipo_dados': kind})


def display(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.3f}'
    return str(value)


def markdown_table(rows, columns):
    if not rows:
        return '[A COLETAR]\n'
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join('---' for _ in columns) + ' |']
    lines += ['| ' + ' | '.join(display(r.get(c)) for c in columns) + ' |' for r in rows]
    return '\n'.join(lines) + '\n'


def report_markdown(report, kind, source_hash):
    label = '**DADOS SINTÉTICOS — validação do instrumento; não são resultados do experimento.**' if kind == 'synthetic' else '**Dados coletados — conferir proveniência e protocolo antes de interpretação.**'
    text = f'# Análise descritiva do experimento\n\n{label}\n\nSnapshot SHA-256: `{source_hash}`.\n\n'
    text += ('MTTR = t5 − t0, em segundos. Usam-se rodadas avaliadas e não descartadas; falhas com '
             'recuperação medida permanecem no resumo. Tentativas sem t5 não recebem zero nem timeout '
             'inventado. Passos são os registrados, inclusive nas falhas. Lacunas são contadas. '
             'O desvio é amostral (n − 1), indisponível com menos de duas observações. '
             'Redução = 100 × (média baseline − média HITL) / média baseline, sem divisão por zero. '
             'Reduções negativas indicam aumento. Não há inferência estatística.\n\n')
    text += '## Cobertura e exclusões\n\n' + markdown_table(report['summary'], SUMMARY_COLUMNS[:9])
    text += '\n## MTTR\n\n' + markdown_table(report['summary'],
        ('cenario', 'braco', 'mttr_n', 'mttr_media_s', 'mttr_desvio_s', 'mttr_min_s', 'mttr_max_s'))
    text += '\n## Passos manuais\n\n' + markdown_table(report['summary'],
        ('cenario', 'braco', 'passos_n', 'passos_media', 'passos_desvio', 'passos_min', 'passos_max'))
    text += '\n## Comparação entre braços\n\n' + markdown_table(report['comparison'],
        ('cenario', 'mttr_n_baseline', 'mttr_n_hitl', 'mttr_reducao_pct', 'passos_n_baseline',
         'passos_n_hitl', 'passos_reducao_pct'))
    text += ('\nOs resumos acima usam todas as medidas elegíveis de cada braço, com n explícito. '
             'A comparação pareada abaixo usa apenas repetições com medida nos dois braços do mesmo cenário; '
             'pares ausentes e médias dos subconjuntos estão em `comparacao.csv`.\n\n')
    text += markdown_table(report['comparison'], ('cenario', 'mttr_pares', 'mttr_pareado_reducao_pct',
                                                  'passos_pares', 'passos_pareado_reducao_pct'))
    text += '\n## Acerto HITL\n\n' + markdown_table(report['accuracy'], TABLES['accuracy'][1])
    text += '\nO agregado divide a soma de sucessos pela soma de tentativas; não faz média de percentuais.\n'
    text += '\n## Decomposição HITL\n\n' + markdown_table(report['phases'], PHASE_COLUMNS)
    text += ('\nA decomposição usa seu próprio subconjunto completo e cronológico, com vínculo único '
             'à auditoria. A média total dessa tabela usa o mesmo subconjunto dos segmentos. '
             'Processamento/apresentação (t3 − t2) inclui a apresentação do card; não mede isoladamente '
             'o motor. Lacunas/ambiguidade estão em `decomposicao_incompleta` de `resumo.csv`. '
             'A cronologia do baseline não é reconstruída a partir de registros HITL.\n')
    return text


def export_report(rows, output: Path, *, kind: str, graphs=True):
    if kind not in ('synthetic', 'collected'):
        raise ValueError('explicit data kind required')
    if output.exists():
        raise FileExistsError('report destination already exists')
    rows = list(rows)
    if any(r.get('tipo_dados') == 'synthetic' for r in rows) and kind != 'synthetic':
        raise ValueError('synthetic snapshot cannot be relabeled as collected')
    if any(r.get('tipo_dados') not in (None, '', 'synthetic', 'collected') for r in rows):
        raise ValueError('invalid data kind in snapshot')
    if rows and isinstance(rows[0].get('id'), str):
        rows = normalize_rows(rows)
    report = analyze(rows)
    raw = []
    for row in rows:
        entry = csv_row({c: row.get(c) for c in COLUMNS})
        for key in AUDIT_COLUMNS:
            value = row.get(key)
            entry[key] = value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) and value.utcoffset() is not None else value
        raw.append(entry)
    snapshot_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    try:
        write_csv(output / 'rodadas.csv', raw, (*COLUMNS, 'mttr_segundos', *AUDIT_COLUMNS), kind)
        for key, (filename, columns) in TABLES.items():
            write_csv(output / filename, report[key], columns, kind)
        (output / 'resultados.md').write_text(report_markdown(report, kind, snapshot_hash), encoding='utf-8')
        if graphs:
            from experiment.analysis.graficos import render_figures
            render_figures(report, output, kind=kind)
        manifest = dict(schema_version=1, tipo_dados=kind, source_sha256=snapshot_hash,
                        rounds=len(rows), files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                for p in sorted(output.iterdir())})
        (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    except BaseException:
        # Remove apenas o diretório recém-criado; evidências anteriores foram recusadas.
        shutil.rmtree(output)
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='CSV snapshot; omit for read-only DB query')
    parser.add_argument('--output', type=Path, required=True, help='new report directory')
    parser.add_argument('--kind', choices=('synthetic', 'collected'), required=True)
    parser.add_argument('--no-graphs', action='store_true')
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        if args.input:
            source = args.input if args.input.is_absolute() else ROOT / args.input
            with source.open(newline='', encoding='utf-8') as stream:
                rows = normalize_rows(csv.DictReader(stream))
        else:
            with conectar() as connection:
                rows = read_snapshot(connection)
        export_report(rows, output, kind=args.kind, graphs=not args.no_graphs)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f'Analysis aborted: {detail}.', file=sys.stderr)
        return 2
    print(f'Exported {args.kind} report to {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
