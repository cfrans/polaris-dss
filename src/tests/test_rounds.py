"""Offline lifecycle checks; PostgreSQL locking and transport need laboratory rehearsal."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from experiment import rounds

START = datetime(2026, 10, 6, tzinfo=timezone.utc)
NOW = START + timedelta(seconds=60)
METADATA = rounds.RoundMetadata('service_down', 'hitl', 1, '0.4.0', 'a' * 40,
                                '1.0.1', '192.0.2.152', 'operator')
ASSESSMENT = rounds.Assessment(0, '', True, 'Human diagnosis and collateral review recorded')


def round_row(**changes):
    row = dict(id=1, cenario='service_down', braco='hitl', ts_injecao=START,
               ts_verificado_ok=START + timedelta(seconds=30), host_alvo='192.0.2.152',
               versao_kb='1.0.1', descartada=False, motivo_descarte=None,
               passos_manuais=None, comandos_usados=None, resolvido=None, observacoes=None)
    row.update(changes)
    return row


def incident_row(**changes):
    row = dict(id=2, id_evento='event-3', hostname='target', ip_address='192.0.2.152',
               ts_deteccao=START + timedelta(seconds=2), ts_criacao=START + timedelta(seconds=3),
               versao_kb='1.0.1', experiment_run_id=None, regra_disparada='R003',
               decisao_humana=True, ts_aprovacao=START + timedelta(seconds=5),
               status_execucao='sucesso', exit_code=0)
    row.update(changes)
    return row


class Connection:
    """Reject unknown SQL and roll back state; do not emulate PostgreSQL concurrency."""
    def __init__(self, row=None, incidents=None, fail_insert=False, fail_commit=False):
        self.row = round_row() if row is None else row
        self.incidents = [incident_row()] if incidents is None else incidents
        self.autocommit = False
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.calls, self.events = [], []
        self.fail_insert, self.fail_commit = fail_insert, fail_commit
        self.result = None

    @contextmanager
    def transaction(self):
        before = deepcopy((self.row, self.incidents))
        self.events.append('begin')
        self.info.transaction_status = TransactionStatus.INTRANS
        try:
            yield
            if self.fail_commit:
                raise OSError('commit failed')
        except BaseException:
            self.row, self.incidents = before
            self.events.append('rollback')
            raise
        else:
            self.events.append('commit')
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        assert self.info.transaction_status == TransactionStatus.INTRANS
        if sql.startswith('INSERT INTO experiment_run'):
            if self.fail_insert:
                raise OSError('insert failed')
            self.result = {'id': 1}
        elif sql.startswith('SELECT * FROM experiment_run'):
            assert 'FOR UPDATE' in sql
            self.result = self.row if params == (1,) else None
        elif sql == 'SELECT clock_timestamp() AS now':
            self.result = {'now': NOW}
        elif sql.startswith('SELECT * FROM audit_log WHERE id ='):
            assert 'FOR UPDATE' in sql
            self.result = next((x for x in self.incidents if x['id'] == params[0]), None)
        elif sql.startswith('SELECT id FROM audit_log WHERE experiment_run_id'):
            self.result = [dict(id=x['id']) for x in self.incidents if x['experiment_run_id'] == params[0]]
        elif sql.startswith('SELECT * FROM audit_log WHERE experiment_run_id'):
            assert 'FOR UPDATE' in sql
            self.result = [x for x in self.incidents if x['experiment_run_id'] == params[0]]
        elif sql.startswith('UPDATE audit_log SET experiment_run_id'):
            assert 'AND experiment_run_id IS NULL RETURNING id' in sql
            incident = next(x for x in self.incidents if x['id'] == params[1])
            if incident['experiment_run_id'] is None:
                incident['experiment_run_id'] = params[0]
                self.result = {'id': incident['id']}
            else:
                self.result = None
        elif sql.startswith('UPDATE experiment_run SET passos_manuais'):
            self.row.update(zip(rounds.MANUAL_FIELDS, params[:4]))
        elif sql.startswith('UPDATE experiment_run SET descartada'):
            self.row.update(descartada=True, motivo_descarte=params[0])
        else:
            pytest.fail(f'Unexpected SQL: {sql}')

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result

    def updates(self):
        return [(sql, params) for sql, params in self.calls if sql.startswith('UPDATE')]


@pytest.mark.parametrize('changes', [
    {'scenario': 'unknown'}, {'arm': 'auto'}, {'repetition': True}, {'repetition': 0},
    {'repetition': 32768}, {'commit_sha': 'abc'}, {'commit_sha': None},
    {'system_version': ''}, {'kb_version': 'x' * 17}, {'target': 'x' * 129},
    {'operator': 'nul\x00name'},
])
def test_invalid_metadata_never_reaches_database_or_injection(changes):
    connection = Connection()
    with pytest.raises(ValueError):
        rounds.register_injection(connection, replace(METADATA, **changes),
                                  lambda run_id: pytest.fail('must not inject'))
    assert connection.calls == []


def test_committed_t0_precedes_callback_and_uses_database_clock():
    connection = Connection()

    def inject(run_id):
        assert run_id == 1
        assert connection.events == ['begin', 'commit']
        assert connection.info.transaction_status == TransactionStatus.IDLE
        connection.events.append('inject')

    assert rounds.register_injection(connection, METADATA, inject) == 1
    sql, params = connection.calls[0]
    assert 'clock_timestamp()' in sql and 'ts_injecao' in sql
    assert params == ('service_down', 'hitl', 1, '0.4.0', 'a' * 40, '1.0.1', '192.0.2.152', 'operator')
    assert connection.events[-1] == 'inject'


@pytest.mark.parametrize('failure', ['fail_insert', 'fail_commit'])
def test_failed_persistence_cannot_inject(failure):
    connection = Connection(**{failure: True})
    with pytest.raises(OSError):
        rounds.register_injection(connection, METADATA, lambda run_id: pytest.fail('must not inject'))
    assert connection.events[-1] == 'rollback'


@pytest.mark.parametrize('error', [RuntimeError('secret detail'), KeyboardInterrupt(), SystemExit(1)])
def test_failed_injection_preserves_round_id_and_discards_without_exception_details(error):
    connection = Connection()

    def inject(run_id):
        assert run_id == 1
        raise error

    with pytest.raises(rounds.InjectionFailed) as exc:
        rounds.register_injection(connection, METADATA, inject)
    assert exc.value.run_id == 1
    assert connection.row['descartada'] is True
    assert type(error).__name__ in connection.row['motivo_descarte']
    assert 'secret detail' not in connection.row['motivo_descarte']
    assert connection.row['ts_injecao'] == START


def test_injection_cannot_return_an_ignored_failure_code():
    connection = Connection()
    with pytest.raises(rounds.InjectionFailed):
        rounds.register_injection(connection, METADATA, lambda run_id: 1)
    assert connection.row['descartada'] is True


def test_failed_discard_after_injection_failure_is_reported(monkeypatch):
    def unavailable(*args):
        raise OSError('database unavailable')

    monkeypatch.setattr(rounds, 'discard_round', unavailable)
    with pytest.raises(rounds.InjectionFailed, match='discard was not persisted') as exc:
        rounds.register_injection(Connection(), METADATA, lambda run_id: 2)
    assert exc.value.run_id == 1


@pytest.mark.parametrize('bad_state', ['autocommit', 'in_transaction'])
def test_helpers_refuse_to_commit_unrelated_transactions(bad_state):
    connection = Connection()
    if bad_state == 'autocommit':
        connection.autocommit = True
    else:
        connection.info.transaction_status = TransactionStatus.INTRANS
    for action in (lambda: rounds.register_injection(connection, METADATA, lambda run_id: None),
                   lambda: rounds.link_incident(connection, 1, 2, 'event-3'),
                   lambda: rounds.assess_round(connection, 1, ASSESSMENT),
                   lambda: rounds.discard_round(connection, 1, 'invalid measurement')):
        with pytest.raises(rounds.RoundError, match='dedicated idle'):
            action()
    assert connection.calls == []


def test_explicit_link_is_idempotent_and_changes_only_the_foreign_key():
    connection = Connection()
    original = deepcopy(connection.incidents[0])
    assert rounds.link_incident(connection, 1, 2, 'event-3') is True
    assert rounds.link_incident(connection, 1, 2, 'event-3') is True
    assert connection.incidents[0] == dict(original, experiment_run_id=1)
    assert len(connection.updates()) == 1
    assert connection.row == round_row()


def test_wrong_rule_is_linked_and_remains_a_failure_in_the_sample():
    connection = Connection(incidents=[incident_row(regra_disparada='R002')])
    assert rounds.link_incident(connection, 1, 2, 'event-3') is False
    assert connection.incidents[0]['experiment_run_id'] == 1
    with pytest.raises(rounds.RoundError):
        rounds.assess_round(connection, 1, ASSESSMENT)
    rounds.assess_round(connection, 1, replace(ASSESSMENT, resolved=False))
    assert connection.row['resolvido'] is False
    assert connection.row['descartada'] is False


@pytest.mark.parametrize('changes', [
    {'id_evento': 'other'}, {'ip_address': '192.0.2.9'}, {'versao_kb': '1.0.0'},
    {'experiment_run_id': 10}, {'ts_deteccao': None},
    {'ts_deteccao': START - timedelta(seconds=1)},
    {'ts_criacao': START + timedelta(seconds=31)},
    {'ts_deteccao': START.replace(tzinfo=None)},
    {'ts_deteccao': START + timedelta(seconds=4)},
])
def test_incompatible_incident_never_changes_link(changes):
    connection = Connection(incidents=[incident_row(**changes)])
    with pytest.raises(rounds.RoundError):
        rounds.link_incident(connection, 1, 2, 'event-3')
    assert connection.updates() == []
    assert connection.events[-1] == 'rollback'


@pytest.mark.parametrize('changes', [
    {'braco': 'baseline'}, {'descartada': True}, {'resolvido': False},
    {'passos_manuais': 0}, {'comandos_usados': ''}, {'observacoes': 'already assessed'},
    {'ts_injecao': NOW + timedelta(seconds=1), 'ts_verificado_ok': None},
])
def test_closed_or_incompatible_round_cannot_link(changes):
    connection = Connection(row=round_row(**changes))
    with pytest.raises(rounds.RoundError):
        rounds.link_incident(connection, 1, 2, 'event-3')
    assert connection.updates() == []


def test_round_and_incident_cannot_be_reassigned():
    connection = Connection(incidents=[incident_row(), incident_row(id=4, experiment_run_id=1)])
    with pytest.raises(rounds.RoundError, match='another incident'):
        rounds.link_incident(connection, 1, 2, 'event-3')
    assert connection.updates() == []


def test_named_target_and_canonical_ipv6_match():
    assert rounds.target_matches('target', incident_row())
    assert not rounds.target_matches('other', incident_row())
    assert rounds.target_matches('2001:db8::1', incident_row(ip_address='2001:0db8:0:0:0:0:0:1'))
    assert not rounds.target_matches('192.0.2.152', incident_row(ip_address=None))


@pytest.mark.parametrize('changes', [
    {'manual_steps': True}, {'manual_steps': -1}, {'manual_steps': 32768},
    {'resolved': 'true'}, {'observations': ''}, {'commands': None},
])
def test_invalid_assessment_has_no_database_effect(changes):
    connection = Connection()
    with pytest.raises(ValueError):
        rounds.assess_round(connection, 1, replace(ASSESSMENT, **changes))
    assert connection.calls == []


@pytest.mark.parametrize('arm', ['baseline', 'hitl'])
def test_assessment_preserves_measured_times_and_literal_commands(arm):
    connection = Connection(row=round_row(braco=arm),
                            incidents=[incident_row(experiment_run_id=1)])
    commands = 'systemctl status nginx\nsudo systemctl restart nginx'
    rounds.assess_round(connection, 1, replace(ASSESSMENT, manual_steps=5, commands=commands))
    assert connection.row == round_row(braco=arm, passos_manuais=5, comandos_usados=commands,
                                     resolvido=True, observacoes=ASSESSMENT.observations)
    assert 'ts_' not in connection.updates()[0][0]
    with pytest.raises(rounds.RoundError, match='already assessed'):
        rounds.assess_round(connection, 1, replace(ASSESSMENT, resolved=False))


@pytest.mark.parametrize('timestamp', [None, START - timedelta(seconds=1),
                                        NOW + timedelta(seconds=1), START.replace(tzinfo=None)])
def test_success_requires_valid_measured_recovery(timestamp):
    connection = Connection(row=round_row(braco='baseline', ts_verificado_ok=timestamp))
    with pytest.raises(rounds.RoundError, match='measured recovery'):
        rounds.assess_round(connection, 1, ASSESSMENT)
    assert connection.updates() == []


@pytest.mark.parametrize('changes', [
    {'decisao_humana': False}, {'decisao_humana': None}, {'ts_aprovacao': None},
    {'ts_aprovacao': START}, {'ts_aprovacao': START + timedelta(seconds=31)},
    {'status_execucao': 'rejeitado'}, {'exit_code': 1}, {'regra_disparada': 'R002'},
    {'ip_address': '192.0.2.9'}, {'versao_kb': '1.0.0'},
])
def test_hitl_success_requires_matching_approved_successful_incident(changes):
    connection = Connection(incidents=[incident_row(experiment_run_id=1, **changes)])
    with pytest.raises(rounds.RoundError):
        rounds.assess_round(connection, 1, ASSESSMENT)
    assert connection.updates() == []


@pytest.mark.parametrize('incidents', [[], [incident_row(experiment_run_id=1),
                                         incident_row(id=4, experiment_run_id=1)]])
def test_hitl_success_requires_exactly_one_incident(incidents):
    connection = Connection(incidents=incidents)
    with pytest.raises(rounds.RoundError, match='exactly one'):
        rounds.assess_round(connection, 1, ASSESSMENT)
    assert connection.updates() == []


def test_failed_resolution_can_be_finalized_without_a_detection_or_recovery():
    connection = Connection(row=round_row(ts_verificado_ok=None), incidents=[])
    rounds.assess_round(connection, 1, replace(ASSESSMENT, resolved=False))
    assert connection.row['resolvido'] is False
    assert connection.row['ts_verificado_ok'] is None
    assert connection.row['descartada'] is False


def test_discard_keeps_measurement_assessment_and_incident_and_cannot_replace_reason():
    connection = Connection(row=round_row(resolvido=False),
                            incidents=[incident_row(experiment_run_id=1)])
    original = deepcopy(connection.row)
    rounds.discard_round(connection, 1, 'observer lost connectivity')
    rounds.discard_round(connection, 1, 'observer lost connectivity')
    assert connection.row == dict(original, descartada=True, motivo_descarte='observer lost connectivity')
    assert len(connection.updates()) == 1
    assert connection.incidents[0] == incident_row(experiment_run_id=1)
    with pytest.raises(rounds.RoundError, match='cannot be replaced'):
        rounds.discard_round(connection, 1, 'different reason')


def test_unknown_round_cannot_be_assessed_or_discarded():
    for operation in (lambda: rounds.assess_round(Connection(), 20, ASSESSMENT),
                      lambda: rounds.discard_round(Connection(), 20, 'reason')):
        with pytest.raises(rounds.RoundError, match='does not exist'):
            operation()


def test_invalid_json_assessment_never_opens_database(tmp_path, monkeypatch, capsys):
    record_file = tmp_path / 'assessment.json'
    record_file.write_text(json.dumps({'passos_manuais': 1}))
    monkeypatch.setattr(rounds, 'conectar', lambda run_id: pytest.fail('must not connect'))
    assert rounds.main(['assess', '--run-id', '1', '--record-file', str(record_file)]) == 2
    assert 'four manual fields' in capsys.readouterr().err


def test_cli_assessment_reads_literal_commands_without_executing_them(tmp_path, monkeypatch):
    connection = Connection(row=round_row(braco='baseline'))
    record_file = tmp_path / 'assessment.json'
    commands = 'literal $(command)\nsecond command'
    record_file.write_text(json.dumps(dict(passos_manuais=2, comandos_usados=commands,
                                         resolvido=True, observacoes='operator review')))

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(rounds, 'conectar', connect)
    assert rounds.main(['assess', '--run-id', '1', '--record-file', str(record_file)]) == 0
    assert connection.row['comandos_usados'] == commands


def test_cli_reports_linked_wrong_rule_without_hiding_it(monkeypatch, capsys):
    connection = Connection(incidents=[incident_row(regra_disparada='R002')])

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(rounds, 'conectar', connect)
    assert rounds.main(['link', '--run-id', '1', '--incident-id', '2', '--event-id', 'event-3']) == 0
    assert json.loads(capsys.readouterr().out)['expected_rule'] is False
