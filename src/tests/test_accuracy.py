"""Accuracy denominator regression checks with synthetic rounds, never research results."""
from decimal import Decimal
import csv

import pytest

from experiment.analysis.accuracy import calculate_accuracy, export_accuracy
from src.db.migrate import descobrir


def row(**changes):
    value = dict(cenario='service_down', braco='hitl', descartada=False, resolvido=False)
    value.update(changes)
    return value


def test_accuracy_counts_false_negatives_wrong_rules_and_rejections_as_attempts():
    # Classification is the human assessment, regardless of operational status/link.
    data = [row(resolvido=True), row(incident=None),
            row(regra_disparada='R002', status_execucao='sucesso'),
            row(status_execucao='rejeitado'), row(resolvido=None),
            row(descartada=True, resolvido=True), row(braco='baseline', resolvido=True)]
    assert calculate_accuracy(data) == [dict(cenario='service_down', tentativas=4,
                                            sucessos=1, taxa_acerto_pct=Decimal('25.0'))]


def test_accuracy_separates_scenarios_and_rounds_half_up_like_postgresql():
    data = [row(cenario='disk_full', resolvido=True)] + [row(cenario='disk_full')] * 15
    data += [row(cenario='cpu_high', resolvido=True)] * 2 + [row(cenario='cpu_high')]
    assert calculate_accuracy(data) == [
        dict(cenario='cpu_high', tentativas=3, sucessos=2, taxa_acerto_pct=Decimal('66.7')),
        dict(cenario='disk_full', tentativas=16, sucessos=1, taxa_acerto_pct=Decimal('6.3')),
    ]


def test_empty_or_unassessed_data_does_not_fabricate_accuracy():
    assert calculate_accuracy([]) == []
    assert calculate_accuracy([row(resolvido=None), row(descartada=True)]) == []


@pytest.mark.parametrize('changes', [dict(resolvido='false'), dict(descartada='false'),
                                     dict(braco='automatic'), dict(cenario='unknown')])
def test_invalid_classification_is_refused(changes):
    with pytest.raises(ValueError):
        calculate_accuracy([row(**changes)])


def test_export_keeps_existing_snapshots_and_has_explicit_header(tmp_path):
    output = tmp_path / 'accuracy.csv'
    export_accuracy([row(resolvido=True), row()], output)
    with output.open(newline='') as stream:
        assert list(csv.DictReader(stream)) == [dict(cenario='service_down', tentativas='2',
                                                   sucessos='1', taxa_acerto_pct='50.0')]
    original = output.read_text()
    with pytest.raises(FileExistsError):
        export_accuracy([], output)
    assert output.read_text() == original


def test_invalid_data_cannot_leave_a_partial_file(tmp_path):
    output = tmp_path / 'accuracy.csv'
    with pytest.raises(ValueError):
        export_accuracy([row(), row(resolvido='false')], output)
    assert not output.exists()


def test_accuracy_view_counts_assessments_in_postgresql(conn):
    migration = next(item for item in descobrir() if item.versao == '007')
    with conn.cursor() as cursor:
        cursor.execute(migration.sql)
        samples = [('hitl', False, True), ('hitl', False, False), ('hitl', False, False),
                   ('hitl', False, None), ('hitl', True, True), ('baseline', False, True)]
        ids = []
        for repetition, (arm, discarded, resolved) in enumerate(samples, 1):
            cursor.execute('INSERT INTO experiment_run (cenario, braco, rodada, descartada, '
                           'ts_injecao, resolvido) VALUES (%s, %s, %s, %s, clock_timestamp(), %s) RETURNING id',
                           ('service_down', arm, repetition, discarded, resolved))
            ids.append(cursor.fetchone()['id'])
        # An approved operational success with the wrong rule must remain a failed round.
        cursor.execute("INSERT INTO audit_log (id_evento, regra_disparada, status_execucao, "
                       "decisao_humana, ts_aprovacao, experiment_run_id) "
                       "VALUES ('synthetic-wrong-rule', 'R002', 'sucesso', TRUE, clock_timestamp(), %s)",
                       (ids[2],))
        cursor.execute('SELECT * FROM vw_kpi03_acerto')
        assert cursor.fetchall() == [dict(cenario='service_down', tentativas=3,
                                         sucessos=1, taxa_acerto_pct=Decimal('33.3'))]
    conn.rollback()
