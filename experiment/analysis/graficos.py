"""Standalone publication figures; Matplotlib is confined to experiment analysis."""
from __future__ import annotations

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt

LABELS = {'disk_full': 'Disco', 'cpu_high': 'CPU', 'service_down': 'Serviço', 'agregado': 'Agregado'}
COLORS = {'baseline': '#52657a', 'hitl': '#087f8c'}


def save(figure, output, name, kind):
    label = 'DADOS SINTÉTICOS — TESTE DO INSTRUMENTO' if kind == 'synthetic' else 'Dados coletados — análise descritiva'
    figure.text(.5, .012, label, ha='center', fontsize=9, color='#a52727' if kind == 'synthetic' else '#52657a')
    figure.tight_layout(rect=(0, .055, 1, 1))
    try:
        figure.savefig(output / f'{name}.png', dpi=300)
        figure.savefig(output / f'{name}.pdf')
    finally:
        plt.close(figure)


def render_figures(report, output, *, kind):
    with plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'pdf.fonttype': 42}):
        for metric, title, unit in (('mttr', 'MTTR por cenário e braço', 'Segundos'),
                                    ('passos', 'Passos manuais por cenário e braço', 'Passos')):
            values = [r for r in report['summary'] if r[metric + '_n']]
            if not values:
                continue
            figure, axis = plt.subplots(figsize=(8, 4.8))
            scenarios = sorted({r['cenario'] for r in values})
            for arm, offset in (('baseline', -.19), ('hitl', .19)):
                for row in values:
                    if row['braco'] != arm:
                        continue
                    x = scenarios.index(row['cenario']) + offset
                    suffix = '_s' if metric == 'mttr' else ''
                    value = row[f'{metric}_media{suffix}']
                    deviation = row[f'{metric}_desvio{suffix}']
                    axis.bar(x, value, width=.34, color=COLORS[arm],
                             yerr=deviation, capsize=4, label=arm if row is next(r for r in values if r['braco'] == arm) else None)
                    axis.annotate(f'n={row[metric+"_n"]}', (x, value + (deviation or 0)),
                                  xytext=(0, 5), textcoords='offset points', ha='center', fontsize=9)
            axis.set_xticks(range(len(scenarios)), [LABELS[s] for s in scenarios])
            axis.set(title=title, ylabel=unit)
            axis.set_ylim(bottom=0)
            axis.margins(y=.2)
            axis.legend(title='Barras: média; hastes: desvio amostral', fontsize=9)
            save(figure, output, metric, kind)
        if report['accuracy']:
            figure, axis = plt.subplots(figsize=(8, 4.8))
            rows = report['accuracy']
            axis.bar(range(len(rows)), [r['taxa_acerto_pct'] for r in rows], color=COLORS['hitl'])
            for x, row in enumerate(rows):
                axis.text(x, row['taxa_acerto_pct'] + 2, f'{row["sucessos"]}/{row["tentativas"]}', ha='center')
            axis.set_xticks(range(len(rows)), [LABELS[r['cenario']] for r in rows])
            axis.set(title='Acerto das rodadas HITL avaliadas', ylabel='Acerto (%)', ylim=(0, 112))
            save(figure, output, 'acerto', kind)
        if report['phases']:
            figure, axis = plt.subplots(figsize=(9, 5.5))
            rows = report['phases']
            bottom = [0.0] * len(rows)
            for field, label in (('deteccao_s', 'Detecção'), ('ingestao_s', 'Ingestão'),
                                 ('processamento_exibicao_s', 'Processamento/apresentação'),
                                 ('decisao_humana_s', 'Decisão humana'),
                                 ('execucao_recuperacao_s', 'Execução/restabelecimento')):
                values = [r[field] for r in rows]
                axis.bar(range(len(rows)), values, bottom=bottom, label=label)
                bottom = [a+b for a, b in zip(bottom, values)]
            axis.set_xticks(range(len(rows)), [f'{LABELS[r["cenario"]]} (n={r["n"]})' for r in rows])
            axis.set(title='Decomposição média do MTTR HITL — cronologias completas', ylabel='Segundos')
            axis.legend(loc='upper left', bbox_to_anchor=(1, 1), fontsize=9)
            save(figure, output, 'decomposicao', kind)
