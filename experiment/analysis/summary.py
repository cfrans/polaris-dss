"""Descriptive KPIs from assessed rounds, without imputing missing measurements."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
from statistics import mean, stdev

from experiment.analysis.consolidar import COLUMNS, csv_row
from experiment.rounds import EXPECTED_RULES, RoundMetadata

AUDIT_COLUMNS = ('incident_id', 'audit_count', 'id_evento', 'regra_disparada',
                 'ts_deteccao', 'ts_criacao', 'ts_exibicao', 'ts_aprovacao')
PHASE_COLUMNS = ('deteccao_s', 'ingestao_s', 'processamento_exibicao_s',
                 'decisao_humana_s', 'execucao_recuperacao_s')
COHORT_COLUMNS = ('versao_sistema', 'commit_sha', 'versao_kb', 'host_alvo', 'operador')


def normalize_rows(rows):
    """Decode the standard CSV snapshot; never interpret blank measurements as zero."""
    decoded = []
    for original in rows:
        row = {key: original.get(key) for key in (*COLUMNS, *AUDIT_COLUMNS, 'tipo_dados')}
        for key in ('id', 'rodada', 'passos_manuais', 'incident_id', 'audit_count'):
            value = row[key]
            if value in (None, ''):
                row[key] = 0 if key == 'audit_count' else None
            elif isinstance(value, str):
                if not value.isascii() or not value.isdigit():
                    raise ValueError(f'invalid integer: {key}')
                row[key] = int(value)
        for key in ('descartada', 'resolvido'):
            value = row[key]
            if isinstance(value, str):
                if value not in ('True', 'False', 'true', 'false', ''):
                    raise ValueError(f'invalid boolean: {key}')
                row[key] = None if value == '' else value.lower() == 'true'
        for key in ('ts_injecao', 'ts_verificado_ok', 'ts_deteccao', 'ts_criacao',
                    'ts_exibicao', 'ts_aprovacao'):
            value = row[key]
            row[key] = datetime.fromisoformat(value) if isinstance(value, str) and value else value or None
        decoded.append(row)
    return decoded


def statistics(values):
    if not values:
        return dict(n=0, media=None, desvio=None, minimo=None, maximo=None)
    return dict(n=len(values), media=mean(values), desvio=stdev(values) if len(values) > 1 else None,
                minimo=min(values), maximo=max(values))


def reduction(baseline, hitl):
    if baseline is None or hitl is None or baseline == 0:
        return None
    return (baseline - hitl) * 100 / baseline


def phase_values(row):
    if row['braco'] != 'hitl' or row.get('audit_count', 0) != 1 or not row.get('incident_id'):
        return None
    timeline = [row.get(key) for key in ('ts_injecao', 'ts_deteccao', 'ts_criacao',
                                       'ts_exibicao', 'ts_aprovacao', 'ts_verificado_ok')]
    if any(not isinstance(t, datetime) or t.utcoffset() is None for t in timeline):
        return None
    if any(end < start for start, end in zip(timeline, timeline[1:])):
        return None
    return [(end - start).total_seconds() for start, end in zip(timeline, timeline[1:])]


def analyze(rows):
    rows = list(rows)
    identities, repetitions, cohorts = set(), set(), set()
    grouped = defaultdict(list)
    for row in rows:
        if type(row.get('id')) is not int or row['id'] <= 0 or row['id'] in identities:
            raise ValueError('invalid or duplicate round ID')
        identities.add(row['id'])
        if row.get('cenario') not in EXPECTED_RULES or row.get('braco') not in ('baseline', 'hitl'):
            raise ValueError('invalid scenario or arm')
        if type(row.get('rodada')) is not int or row['rodada'] <= 0:
            raise ValueError('invalid repetition')
        if type(row.get('descartada')) is not bool or (row.get('resolvido') is not None
                                                       and type(row['resolvido']) is not bool):
            raise ValueError('invalid round assessment')
        steps = row.get('passos_manuais')
        if steps is not None and (type(steps) is not int or not 0 <= steps <= 32767):
            raise ValueError('invalid manual step count')
        csv_row({key: row.get(key) for key in COLUMNS})
        if row.get('resolvido') is True and row.get('ts_verificado_ok') is None:
            raise ValueError('successful assessment without measured recovery')
        if row['descartada'] and not (row.get('motivo_descarte') or '').strip():
            raise ValueError('discard reason missing')
        if not row['descartada']:
            key = (row['cenario'], row['braco'], row['rodada'])
            if key in repetitions:
                raise ValueError('duplicate non-discarded repetition')
            repetitions.add(key)
            if row.get('resolvido') is not None:
                RoundMetadata(row['cenario'], row['braco'], row['rodada'], row.get('versao_sistema'),
                              row.get('commit_sha'), row.get('versao_kb'), row.get('host_alvo'),
                              row.get('operador')).validate()
                cohorts.add(tuple(row[k] for k in COHORT_COLUMNS))
        grouped[row['cenario'], row['braco']].append(row)
    if len(cohorts) > 1:
        raise ValueError('mixed cohort: versions, target or operator differ; export separate cohorts')

    summaries, phases, accuracy = [], [], []
    eligible = {}
    for (scenario, arm), group in sorted(grouped.items()):
        valid = [r for r in group if not r['descartada'] and r.get('resolvido') is not None]
        measured = [r for r in valid if r.get('ts_verificado_ok') is not None]
        steps = [r for r in valid if r.get('passos_manuais') is not None]
        eligible[scenario, arm] = dict(mttr={r['rodada']: (r['ts_verificado_ok']-r['ts_injecao']).total_seconds()
                                           for r in measured},
                                      passos={r['rodada']: r['passos_manuais'] for r in steps})
        timing = statistics(list(eligible[scenario, arm]['mttr'].values()))
        effort = statistics(list(eligible[scenario, arm]['passos'].values()))
        complete_phases = [phase_values(r) for r in measured] if arm == 'hitl' else []
        complete = [values for values in complete_phases if values is not None]
        summaries.append(dict(cenario=scenario, braco=arm, total=len(group),
                              descartadas=sum(r['descartada'] for r in group),
                              nao_avaliadas=sum(not r['descartada'] and r.get('resolvido') is None for r in group),
                              avaliadas=len(valid), falhas=sum(r['resolvido'] is False for r in valid),
                              sem_t5=len(valid)-len(measured), sem_passos=len(valid)-len(steps),
                              mttr_n=timing['n'], mttr_media_s=timing['media'], mttr_desvio_s=timing['desvio'],
                              mttr_min_s=timing['minimo'], mttr_max_s=timing['maximo'],
                              passos_n=effort['n'], passos_media=effort['media'], passos_desvio=effort['desvio'],
                              passos_min=effort['minimo'], passos_max=effort['maximo'],
                              decomposicao_incompleta=len(complete_phases)-len(complete)))
        if complete:
            item = dict(cenario=scenario, n=len(complete), mttr_media_s=mean(sum(v) for v in complete))
            item.update({column: mean(values[i] for values in complete)
                         for i, column in enumerate(PHASE_COLUMNS)})
            phases.append(item)
        if arm == 'hitl' and valid:
            successes = sum(r['resolvido'] for r in valid)
            accuracy.append(dict(cenario=scenario, tentativas=len(valid), sucessos=successes,
                                 taxa_acerto_pct=float((Decimal(successes*100)/len(valid)).quantize(
                                     Decimal('0.1'), rounding=ROUND_HALF_UP))))
    if accuracy:
        attempted, succeeded = sum(r['tentativas'] for r in accuracy), sum(r['sucessos'] for r in accuracy)
        accuracy.append(dict(cenario='agregado', tentativas=attempted, sucessos=succeeded,
                             taxa_acerto_pct=float((Decimal(succeeded*100)/attempted).quantize(
                                 Decimal('0.1'), rounding=ROUND_HALF_UP))))

    comparisons = []
    for scenario in sorted({r['cenario'] for r in rows}):
        item = dict(cenario=scenario)
        for metric in ('mttr', 'passos'):
            base = eligible.get((scenario, 'baseline'), {}).get(metric, {})
            hitl = eligible.get((scenario, 'hitl'), {}).get(metric, {})
            pairs = sorted(base.keys() & hitl.keys())
            base_mean = mean(base.values()) if base else None
            hitl_mean = mean(hitl.values()) if hitl else None
            paired_base = mean(base[k] for k in pairs) if pairs else None
            paired_hitl = mean(hitl[k] for k in pairs) if pairs else None
            item.update({f'{metric}_n_baseline': len(base), f'{metric}_n_hitl': len(hitl),
                         f'{metric}_media_baseline': base_mean, f'{metric}_media_hitl': hitl_mean,
                         f'{metric}_reducao_pct': reduction(base_mean, hitl_mean),
                         f'{metric}_pares': len(pairs), f'{metric}_sem_par_baseline': len(base)-len(pairs),
                         f'{metric}_sem_par_hitl': len(hitl)-len(pairs),
                         f'{metric}_pareado_media_baseline': paired_base,
                         f'{metric}_pareado_media_hitl': paired_hitl,
                         f'{metric}_pareado_reducao_pct': reduction(paired_base, paired_hitl)})
        comparisons.append(item)
    report = dict(summary=summaries, comparison=comparisons, phases=phases, accuracy=accuracy)
    # Resultados não finitos invalidam a análise, inclusive de horários extremos.
    for table in report.values():
        for item in table:
            if any(isinstance(v, float) and not math.isfinite(v) for v in item.values()):
                raise ValueError('non-finite descriptive result')
    return report
