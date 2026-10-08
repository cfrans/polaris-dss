"""Synthetic arithmetic, evidence preservation and local snapshot integration."""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from experiment.analysis.summary import analyze, normalize_rows
from experiment.analysis.report import export_report, read_snapshot, main

START = datetime(2026, 10, 8, tzinfo=timezone.utc)


def sample(run_id=1, arm='baseline', repetition=1, seconds=10, steps=4, **changes):
    row = dict(id=run_id, cenario='service_down', braco=arm, rodada=repetition,
               descartada=False, motivo_descarte=None, versao_sistema='validation',
               commit_sha='a' * 40, versao_kb='1.0.1', host_alvo='synthetic-target',
               operador='synthetic-operator', ts_injecao=START,
               ts_verificado_ok=START + timedelta(seconds=seconds) if seconds is not None else None,
               passos_manuais=steps, comandos_usados='diagnose\nrepair', resolvido=True,
               observacoes='synthetic fixture')
    row.update(changes)
    return row


def test_descriptive_statistics_reductions_and_paired_counts():
    rows = [sample(), sample(2, repetition=2, seconds=20, steps=6),
            sample(3, 'hitl', seconds=5, steps=1),
            sample(4, 'hitl', 2, seconds=15, steps=2)]
    report = analyze(rows)
    base = next(r for r in report['summary'] if r['braco'] == 'baseline')
    assert base['mttr_media_s'] == 15
    assert base['mttr_desvio_s'] == pytest.approx(7.0710678118654755)
    assert (base['mttr_min_s'], base['mttr_max_s']) == (10, 20)
    comparison = report['comparison'][0]
    assert comparison['mttr_reducao_pct'] == pytest.approx(100 / 3)
    assert comparison['passos_reducao_pct'] == 70
    assert comparison['mttr_pares'] == 2
    assert comparison['mttr_pareado_reducao_pct'] == pytest.approx(100 / 3)


def test_failures_missing_values_discards_and_unassessed_remain_visible():
    rows = [sample(1, 'hitl', resolvido=False, seconds=None, steps=3),
            sample(2, 'hitl', 2, seconds=8, steps=2, resolvido=False),
            sample(3, 'hitl', 3, seconds=4, steps=None),
            sample(4, 'hitl', 4, resolvido=None, seconds=2, steps=1),
            sample(5, 'hitl', 5, descartada=True, motivo_descarte='rehearsal')]
    report = analyze(rows)
    row = report['summary'][0]
    assert row['total'] == 5 and row['descartadas'] == 1 and row['nao_avaliadas'] == 1
    assert row['avaliadas'] == 3 and row['falhas'] == 2
    assert row['mttr_n'] == 2 and row['sem_t5'] == 1 and row['mttr_media_s'] == 6
    assert row['passos_n'] == 2 and row['sem_passos'] == 1 and row['passos_media'] == 2.5
    assert report['accuracy'][-1]['tentativas'] == 3
    assert report['accuracy'][-1]['sucessos'] == 1
    assert report['accuracy'][-1]['taxa_acerto_pct'] == pytest.approx(33.3)


def test_missing_arms_zero_baseline_and_single_observation_do_not_invent_results():
    report = analyze([sample(seconds=0, steps=0), sample(2, 'hitl', seconds=5, steps=1)])
    assert report['summary'][0]['mttr_desvio_s'] is None
    assert report['comparison'][0]['mttr_reducao_pct'] is None
    assert report['comparison'][0]['passos_reducao_pct'] is None
    report = analyze([sample()])
    assert report['comparison'][0]['mttr_reducao_pct'] is None
    assert report['comparison'][0]['mttr_pares'] == 0
    assert analyze([])['summary'] == []
    assert analyze([])['accuracy'] == []


@pytest.mark.parametrize('changes', [
    {'ts_injecao': START.replace(tzinfo=None)},
    {'ts_verificado_ok': START - timedelta(seconds=1)},
    {'passos_manuais': -1}, {'passos_manuais': True}, {'resolvido': 'True'},
    {'descartada': 'False'}, {'braco': 'unknown'}, {'rodada': 0},
    {'id': 0}, {'ts_verificado_ok': None, 'resolvido': True},
])
def test_corrupted_input_is_refused(changes):
    with pytest.raises(ValueError):
        analyze([sample(**changes)])


def test_duplicate_rounds_or_mixed_cohort_are_refused_but_discards_preserved():
    with pytest.raises(ValueError, match='duplicate'):
        analyze([sample(), sample(2)])
    with pytest.raises(ValueError, match='cohort'):
        analyze([sample(), sample(2, 'hitl', commit_sha='b' * 40)])
    assert analyze([sample(), sample(2, descartada=True, motivo_descarte='rehearsal',
                                    commit_sha='b' * 40)])['summary'][0]['total'] == 2


def test_decomposition_requires_ordered_complete_unique_hitl_link():
    linked = sample(1, 'hitl', seconds=10, incident_id=7, audit_count=1,
                    ts_deteccao=START + timedelta(seconds=1),
                    ts_criacao=START + timedelta(seconds=2),
                    ts_exibicao=START + timedelta(seconds=4),
                    ts_aprovacao=START + timedelta(seconds=7))
    report = analyze([linked])
    phases = report['phases'][0]
    assert [phases[k] for k in ('deteccao_s', 'ingestao_s', 'processamento_exibicao_s',
                               'decisao_humana_s', 'execucao_recuperacao_s')] == [1, 1, 2, 3, 3]
    assert phases['mttr_media_s'] == 10
    for changes in ({'audit_count': 2}, {'ts_exibicao': None}, {'ts_deteccao': START - timedelta(seconds=1)}):
        result = analyze([{**linked, **changes}])
        assert result['phases'] == []
        assert result['summary'][0]['decomposicao_incompleta'] == 1


def test_csv_report_preserves_evidence_labels_and_never_overwrites(tmp_path):
    rows = [sample(), sample(2, 'hitl', seconds=5, steps=1)]
    target = tmp_path / 'report'
    export_report(rows, target, kind='synthetic', graphs=False)
    with (target / 'rodadas.csv').open(newline='', encoding='utf-8') as stream:
        raw = list(csv.DictReader(stream))
    assert raw[0]['comandos_usados'] == 'diagnose\nrepair'
    assert raw[0]['tipo_dados'] == 'synthetic'
    assert normalize_rows(raw)[0]['ts_injecao'] == START
    assert 'DADOS SINTÉTICOS' in (target / 'resultados.md').read_text()
    with pytest.raises(FileExistsError):
        export_report(rows, target, kind='synthetic', graphs=False)
    with pytest.raises(ValueError, match='synthetic'):
        export_report(raw, tmp_path / 'promoted', kind='collected', graphs=False)
    assert not (tmp_path / 'promoted').exists()


def test_invalid_snapshot_creates_no_report_and_empty_has_no_fake_statistics(tmp_path):
    with pytest.raises(ValueError):
        export_report([sample(passos_manuais=-1)], tmp_path / 'bad', kind='synthetic', graphs=False)
    assert not (tmp_path / 'bad').exists()
    export_report([], tmp_path / 'empty', kind='synthetic', graphs=False)
    assert '[A COLETAR]' in (tmp_path / 'empty' / 'resultados.md').read_text()


def test_real_snapshot_join_is_read_only_and_does_not_duplicate_rounds(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO experiment_run (cenario, braco, rodada, versao_sistema, commit_sha, "
                    "versao_kb, host_alvo, operador, ts_injecao, ts_verificado_ok, passos_manuais, resolvido) "
                    "VALUES ('service_down', 'hitl', 1, 'validation', %s, '1.0.1', 'synthetic-target', "
                    "'synthetic-operator', %s, %s, 1, TRUE) RETURNING id", ('a'*40, START, START+timedelta(seconds=10)))
        run_id = cur.fetchone()['id']
        for event in ('snapshot-1', 'snapshot-2'):
            cur.execute("INSERT INTO audit_log (id_evento, experiment_run_id, status_execucao, ts_deteccao, "
                        "ts_criacao, ts_exibicao, ts_aprovacao) VALUES (%s, %s, 'sucesso', %s, %s, %s, %s)",
                        (event, run_id, START+timedelta(seconds=1), START+timedelta(seconds=2),
                         START+timedelta(seconds=4), START+timedelta(seconds=7)))
    conn.commit()
    rows = read_snapshot(conn)
    assert len(rows) == 1 and rows[0]['audit_count'] == 2
    assert analyze(rows)['phases'] == []
    assert conn.info.transaction_status.name == 'IDLE'
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM audit_log')
        assert cur.fetchone()['n'] == 2
    conn.rollback()


def test_graphs_are_exportable(tmp_path):
    pytest.importorskip('matplotlib')
    rows = [sample(), sample(2, 'hitl', seconds=5, steps=1)]
    export_report(rows, tmp_path / 'figures', kind='synthetic')
    for metric in ('mttr', 'passos', 'acerto'):
        assert (tmp_path / 'figures' / f'{metric}.png').read_bytes().startswith(b'\x89PNG')
        pdf = (tmp_path / 'figures' / f'{metric}.pdf').read_bytes()
        assert pdf.startswith(b'%PDF') and len(pdf) > 1000


def test_offline_cli_uses_csv_without_connecting(tmp_path, monkeypatch):
    export_report([sample()], tmp_path / 'source', kind='synthetic', graphs=False)
    monkeypatch.setattr('experiment.analysis.report.conectar', lambda: pytest.fail('offline input'))
    assert main(['--input', str(tmp_path/'source'/'rodadas.csv'), '--output', str(tmp_path/'dest'),
                 '--kind', 'synthetic', '--no-graphs']) == 0


def test_unmatched_repetitions_are_visible_and_paired_reduction_uses_only_complete_pairs():
    result = analyze([sample(1, repetition=1, seconds=10), sample(2, repetition=2, seconds=100),
                      sample(3, 'hitl', repetition=1, seconds=5)])['comparison'][0]
    assert result['mttr_pares'] == 1 and result['mttr_sem_par_baseline'] == 1
    assert result['mttr_pareado_reducao_pct'] == 50
    assert result['mttr_reducao_pct'] == pytest.approx(100 * 50 / 55)


def test_aggregate_accuracy_is_weighted_by_attempts_not_scenario_percentages():
    rows = [sample(1, 'hitl')]
    rows += [sample(i+2, 'hitl', i+1, cenario='cpu_high', resolvido=False) for i in range(3)]
    assert analyze(rows)['accuracy'][-1] == dict(cenario='agregado', tentativas=4, sucessos=1,
                                                taxa_acerto_pct=25)


def test_render_failure_cleans_only_its_new_report_directory(tmp_path, monkeypatch):
    pytest.importorskip('matplotlib')
    def fail(*args, **kwargs):
        raise OSError('render unavailable')
    monkeypatch.setattr('experiment.analysis.graficos.render_figures', fail)
    preserved = tmp_path / 'prior_evidence.csv'
    preserved.write_text('preserve')
    with pytest.raises(OSError):
        export_report([sample()], tmp_path/'new', kind='synthetic')
    assert not (tmp_path/'new').exists() and preserved.read_text() == 'preserve'
