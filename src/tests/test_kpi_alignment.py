"""Regressions against real PostgreSQL, using synthetic rounds only."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import pytest

from experiment.analysis.report import read_snapshot
from experiment.analysis.summary import analyze, phase_values
from src.db import queries
from src.db.migrate import descobrir

START = datetime(2026, 10, 13, tzinfo=timezone.utc)


def insert_round(conn, repetition, arm='hitl', seconds=10, steps=1, **changes):
    values = dict(cenario='service_down', braco=arm, rodada=repetition,
                  descartada=False, motivo_descarte=None, versao_sistema='validation',
                  commit_sha='a' * 40, versao_kb='1.0.1', host_alvo='synthetic-target',
                  operador='synthetic-operator', ts_injecao=START,
                  ts_verificado_ok=START + timedelta(seconds=seconds) if seconds is not None else None,
                  passos_manuais=steps, resolvido=True)
    values.update(changes)
    with conn.cursor() as cur:
        columns = ', '.join(values)
        placeholders = ', '.join(['%s'] * len(values))
        cur.execute(f'INSERT INTO experiment_run ({columns}) VALUES ({placeholders}) RETURNING id',
                    tuple(values.values()))
        return cur.fetchone()['id']


def insert_incident(conn, run_id, event, **changes):
    values = dict(id_evento=event, experiment_run_id=run_id, regra_disparada='R003',
                  status_execucao='sucesso', decisao_humana=True,
                  ts_deteccao=START + timedelta(seconds=1),
                  ts_criacao=START + timedelta(seconds=2),
                  ts_exibicao=START + timedelta(seconds=4),
                  ts_aprovacao=START + timedelta(seconds=7),
                  # Operational completion is intentionally earlier than independent t5.
                  ts_conclusao=START + timedelta(seconds=8))
    values.update(changes)
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO audit_log ({', '.join(values)}) "
                    f"VALUES ({', '.join(['%s'] * len(values))})", tuple(values.values()))


def snapshot_report(conn):
    conn.commit()
    rows = read_snapshot(conn)
    return rows, analyze(rows)


def rounded(value, digits=1):
    return None if value is None else Decimal(str(value)).quantize(
        Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def test_mttr_and_steps_use_assessed_rounds_and_keep_valid_failures(conn):
    insert_round(conn, 1, 'baseline', seconds=20, steps=4)
    insert_round(conn, 2, 'baseline', seconds=40, steps=8, resolvido=False)
    insert_round(conn, 1, seconds=10)
    insert_round(conn, 2, seconds=20, steps=3, resolvido=False)
    insert_round(conn, 3, seconds=None, steps=5, resolvido=False)
    insert_round(conn, 4, seconds=15, steps=None, resolvido=False)
    insert_round(conn, 5, seconds=900, steps=90, resolvido=None)
    insert_round(conn, 6, seconds=800, steps=80, descartada=True, motivo_descarte='rehearsal')
    _, report = snapshot_report(conn)
    data = queries.kpis(conn)
    comparison = report['comparison'][0]
    timing = data['kpi01_mttr'][0]
    assert timing['n_baseline'] == comparison['mttr_n_baseline'] == 2
    assert timing['n_hitl'] == comparison['mttr_n_hitl'] == 3
    for sql_field, report_field in (
        ('mttr_baseline_s', 'mttr_media_baseline'), ('mttr_hitl_s', 'mttr_media_hitl'),
        ('reducao_pct', 'mttr_reducao_pct'),
    ):
        assert timing[sql_field] == rounded(comparison[report_field])
    for summary in report['summary']:
        effort = next(row for row in data['kpi02_passos'] if row['braco'] == summary['braco'])
        assert effort['n'] == summary['passos_n']
        assert effort['passos_medio'] == rounded(summary['passos_media'], 2)
        assert effort['passos_min'] == summary['passos_min']
        assert effort['passos_max'] == summary['passos_max']
        assert timing['desvio_' + summary['braco'] + '_s'] == rounded(summary['mttr_desvio_s'])
    assert report['summary'][1]['sem_t5'] == report['summary'][1]['sem_passos'] == 1
    assert data['kpi03_acerto'][0]['tentativas'] == 4
    assert data['kpi03_acerto'][0]['sucessos'] == 1


@pytest.mark.parametrize('arm', ['baseline', 'hitl'])
def test_mttr_exposes_existing_arm_without_inventing_the_other(conn, arm):
    insert_round(conn, 1, arm, seconds=10)
    _, report = snapshot_report(conn)
    timing = queries.kpis(conn)['kpi01_mttr']
    assert len(timing) == 1
    row = timing[0]
    missing = 'hitl' if arm == 'baseline' else 'baseline'
    assert row['n_' + arm] == 1
    assert row['n_' + missing] == 0
    assert row['mttr_' + arm + '_s'] == 10
    assert row['mttr_' + missing + '_s'] is None
    assert row['desvio_' + arm + '_s'] is None
    assert row['reducao_pct'] is report['comparison'][0]['mttr_reducao_pct'] is None


def test_zero_baseline_has_no_percentage_and_zero_steps_are_measurements(conn):
    insert_round(conn, 1, 'baseline', seconds=0, steps=0)
    insert_round(conn, 1, seconds=5)
    data = queries.kpis(conn)
    assert data['kpi01_mttr'][0]['reducao_pct'] is None
    assert data['kpi02_passos'][0]['passos_medio'] == 0
    assert data['kpi02_passos'][0]['n'] == 1


def test_unassessed_discarded_and_missing_measurements_produce_no_fake_metrics(conn):
    insert_round(conn, 1, resolvido=None)
    insert_round(conn, 2, descartada=True, motivo_descarte='rehearsal')
    insert_round(conn, 3, seconds=None, steps=None, resolvido=False)
    data = queries.kpis(conn)
    assert data['kpi01_mttr'] == []
    assert data['kpi02_passos'] == []
    assert data['decomposicao_mttr'] == []
    assert data['kpi03_acerto'][0]['tentativas'] == 1


@pytest.mark.parametrize('resolved', [True, False])
def test_phases_end_at_independent_t5_and_sum_to_total(conn, resolved):
    run_id = insert_round(conn, 1, resolvido=resolved)
    insert_incident(conn, run_id, 'synthetic-independent-t5')
    rows, report = snapshot_report(conn)
    values = phase_values(rows[0])
    phase = queries.kpis(conn)['decomposicao_mttr'][0]
    fields = ('deteccao_s', 'ingestao_s', 'inferencia_s', 'decisao_humana_s', 'execucao_s')
    assert [phase[key] for key in fields] == [Decimal(str(value)) for value in values]
    assert phase['execucao_s'] == 3
    assert sum(phase[key] for key in fields) == phase['mttr_total_s'] == report['phases'][0]['mttr_media_s']


def test_slower_assisted_recovery_keeps_a_negative_reduction(conn):
    insert_round(conn, 1, 'baseline', seconds=10)
    insert_round(conn, 1, seconds=20, resolvido=False)
    _, report = snapshot_report(conn)
    assert queries.kpis(conn)['kpi01_mttr'][0]['reducao_pct'] == report['comparison'][0]['mttr_reducao_pct'] == -100


@pytest.mark.parametrize('change', [
    'no_audit', 'duplicate', 'missing_detection', 'missing_display',
    'missing_approval', 'missing_t5', 'detection_before_injection', 'creation_before_detection',
    'display_before_creation', 'approval_before_display', 't5_before_approval',
    'unassessed', 'discarded', 'baseline',
])
def test_phase_exclusions_match_the_snapshot_report(conn, change):
    round_changes = {}
    incident_changes = {}
    if change == 'missing_t5':
        round_changes.update(seconds=None, resolvido=False)
    elif change == 'unassessed':
        round_changes['resolvido'] = None
    elif change == 'discarded':
        round_changes.update(descartada=True, motivo_descarte='rehearsal')
    elif change == 'baseline':
        round_changes['arm'] = 'baseline'
    else:
        incident_changes = {
            'missing_detection': {'ts_deteccao': None},
            'missing_display': {'ts_exibicao': None}, 'missing_approval': {'ts_aprovacao': None},
            'detection_before_injection': {'ts_deteccao': START - timedelta(seconds=1)},
            'creation_before_detection': {'ts_criacao': START},
            'display_before_creation': {'ts_exibicao': START + timedelta(seconds=1)},
            'approval_before_display': {'ts_aprovacao': START + timedelta(seconds=3)},
            't5_before_approval': {'ts_aprovacao': START + timedelta(seconds=11)},
        }.get(change, {})
    run_id = insert_round(conn, 1, **round_changes)
    if change != 'no_audit':
        insert_incident(conn, run_id, 'synthetic-exclusion', **incident_changes)
    if change == 'duplicate':
        insert_incident(conn, run_id, 'synthetic-second-link')
    _, report = snapshot_report(conn)
    assert queries.kpis(conn)['decomposicao_mttr'] == []
    assert report['phases'] == []


def test_api_preserves_fields_and_decimal_serialization_with_nonempty_data(conn, cliente):
    insert_round(conn, 1, 'baseline', seconds=20, steps=4)
    run_id = insert_round(conn, 1)
    insert_incident(conn, run_id, 'synthetic-api')
    _, report = snapshot_report(conn)
    response = cliente.get('/api/v1/kpis')
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {'kpi01_mttr', 'kpi02_passos', 'kpi03_acerto', 'decomposicao_mttr'}
    assert data['kpi01_mttr'] == [dict(cenario='service_down', n_baseline=1, n_hitl=1,
                                    mttr_baseline_s='20.0', mttr_hitl_s='10.0',
                                    desvio_baseline_s=None, desvio_hitl_s=None, reducao_pct='50.0')]
    phase = data['decomposicao_mttr'][0]
    fields = ('deteccao_s', 'ingestao_s', 'inferencia_s', 'decisao_humana_s', 'execucao_s')
    assert sum(Decimal(phase[key]) for key in fields) == Decimal(phase['mttr_total_s'])
    assert Decimal(phase['mttr_total_s']) == report['phases'][0]['mttr_media_s']


def test_alignment_migration_preserves_primary_rows_and_can_be_reapplied(conn):
    run_id = insert_round(conn, 1)
    insert_incident(conn, run_id, 'synthetic-preservation')
    before, _ = snapshot_report(conn)
    expected = queries.kpis(conn)
    def primary_rows():
        with conn.cursor() as cur:
            cur.execute('SELECT to_jsonb(r) AS row FROM experiment_run r ORDER BY id')
            rounds = cur.fetchall()
            cur.execute('SELECT to_jsonb(a) AS row FROM audit_log a ORDER BY id')
            return rounds, cur.fetchall()
    primary_before = primary_rows()
    migration = next(item for item in descobrir() if item.versao == '008')
    with conn.cursor() as cur:
        cur.execute(migration.sql)
        cur.execute(migration.sql)
    after, _ = snapshot_report(conn)
    assert after == before
    assert queries.kpis(conn) == expected
    assert primary_rows() == primary_before
