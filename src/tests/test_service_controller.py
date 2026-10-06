"""Controller and shell regression checks without SSH, Docker or real services."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from experiment.scenarios import service_controller as controller
from experiment.rounds import InjectionFailed
from src.tests.test_rounds import Connection as BaseConnection, METADATA, START, round_row


class Connection(BaseConnection):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target_locked = True
        self.open_runs = []
        self.open_incidents = []

    def execute(self, sql, params=None):
        if 'pg_try_advisory_lock' in sql:
            self.calls.append((sql, params))
            self.result = {'locked': self.target_locked}
        elif 'pg_advisory_unlock' in sql:
            self.calls.append((sql, params))
            self.result = {'unlocked': True}
        elif sql.startswith('SELECT id FROM experiment_run'):
            self.calls.append((sql, params))
            self.result = self.open_runs
        elif sql.startswith('SELECT id FROM audit_log'):
            self.calls.append((sql, params))
            self.result = self.open_incidents
        else:
            super().execute(sql, params)


class Observer:
    def __init__(self, events, error=None):
        self.events, self.error = events, error

    def start(self, run_id):
        self.events.append(('observe', run_id))

    def wait(self):
        self.events.append('wait')
        if self.error:
            raise self.error
        return START + timedelta(seconds=30)

    def stop(self):
        self.events.append('stop_observer')


def test_controller_arms_observer_after_commit_and_before_injection_without_recovering():
    connection, events = Connection(), []

    def action(operation):
        if operation == 'inject':
            assert connection.events[-1] == 'commit'
        events.append(operation)

    outcome = controller.run_round(connection, METADATA, action, lambda: True,
                                   Observer(events), sleep=lambda seconds: events.append(seconds))
    assert outcome == (1, START + timedelta(seconds=30))
    assert events == ['check', 60, 'check', ('observe', 1), 'inject', 'wait', 'stop_observer']
    assert 'reset' not in events
    assert not any('decisao_humana' in sql or 'SET resolvido' in sql for sql, _ in connection.calls)
    assert 'pg_advisory_unlock' in connection.calls[-1][0]


@pytest.mark.parametrize('dirty', ['service', 'round', 'incident', 'locked'])
def test_unclean_environment_cannot_create_or_inject_round(dirty):
    connection, actions = Connection(), []
    if dirty == 'round':
        connection.open_runs = [{'id': 4}]
    elif dirty == 'incident':
        connection.open_incidents = [{'id': 4}]
    elif dirty == 'locked':
        connection.target_locked = False
    with pytest.raises(controller.ScenarioError):
        controller.run_round(connection, METADATA, actions.append, lambda: dirty != 'service',
                             Observer(actions), sleep=lambda _: None)
    assert 'inject' not in actions
    assert not any(sql.startswith('INSERT') for sql, _ in connection.calls)
    if dirty == 'locked':
        assert not any('pg_advisory_unlock' in sql for sql, _ in connection.calls)


def test_injection_failure_discards_evidence_and_never_resets_automatically():
    connection, events = Connection(), []

    def action(operation):
        events.append(operation)
        if operation == 'inject':
            raise controller.ScenarioError('failed stop')

    with pytest.raises(InjectionFailed):
        controller.run_round(connection, METADATA, action, lambda: True, Observer(events), sleep=lambda _: None)
    assert connection.row['descartada'] is True
    assert 'reset' not in events
    assert 'stop_observer' in events


def test_observation_timeout_preserves_round_for_human_failure_assessment():
    connection, events = Connection(), []
    with pytest.raises(controller.ScenarioError, match='Round 1'):
        controller.run_round(connection, METADATA, events.append, lambda: True,
                             Observer(events, TimeoutError()), sleep=lambda _: None)
    assert connection.row['descartada'] is False
    assert connection.row['resolvido'] is None
    assert 'reset' not in events
    assert 'stop_observer' in events


@pytest.mark.parametrize('changes', [{'cenario': 'cpu_high'}, {'host_alvo': 'other'},
                                     {'resolvido': None, 'descartada': False}])
def test_reset_refuses_live_or_incompatible_round(changes):
    connection, actions = Connection(row=round_row(resolvido=False, **changes) if 'resolvido' not in changes
                                     else round_row(**changes)), []
    with pytest.raises(controller.ScenarioError):
        controller.reset_round(connection, 1, METADATA.target, actions.append, lambda: True)
    assert 'reset' not in actions


def test_reset_requires_linked_incident_to_be_closed_and_preserves_evidence():
    connection, actions = Connection(row=round_row(resolvido=False)), []
    connection.open_incidents = [{'id': 2}]
    with pytest.raises(controller.ScenarioError):
        controller.reset_round(connection, 1, METADATA.target, actions.append, lambda: True)
    assert actions == []
    connection.open_incidents = []
    original = connection.row.copy()
    controller.reset_round(connection, 1, METADATA.target, actions.append, lambda: True)
    assert actions == ['reset']
    assert connection.row == original
    assert connection.updates() == []


def test_target_script_uses_only_fixed_actions_and_current_bytes():
    calls = []

    def runner(command, timeout, input_data):
        calls.append((command, timeout, input_data))
        return 0, 'nginx: inactive\n' if command.endswith(' inject') else 'nginx: active\n', ''

    action = controller.AdminTransport(runner)
    action('inject')
    assert calls[0][0] == 'sudo -n /usr/bin/timeout -k 5s 20s /usr/bin/bash -s -- inject'
    assert calls[0][2] == controller.SCRIPT.read_bytes()
    with pytest.raises(ValueError):
        action('inject; systemctl stop other')
    assert len(calls) == 1


@pytest.mark.parametrize('result', [(124, '', ''), (1, 'nginx: inactive', ''), (0, 'unexpected', '')])
def test_transport_failure_is_never_reported_as_success(result):
    action = controller.AdminTransport(lambda *args, **kwargs: result)
    with pytest.raises(controller.ScenarioError):
        action('inject')


def test_admin_identity_cannot_reuse_service_identity_or_key(tmp_path):
    key = tmp_path / 'key'
    with pytest.raises(ValueError):
        controller.validate_admin('polaris', key, 'polaris', tmp_path / 'service_key')
    with pytest.raises(ValueError):
        controller.validate_admin('administrator', key, 'polaris', key)
    controller.validate_admin('administrator', key, 'polaris', tmp_path / 'service_key')


@pytest.mark.parametrize('scenario', ['disk_full', 'cpu_high'])
def test_controller_only_accepts_r003(scenario):
    with pytest.raises(ValueError):
        controller.run_round(Connection(), replace(METADATA, scenario=scenario),
                             lambda _: pytest.fail('no remote action'), lambda: True,
                             Observer([]), sleep=lambda _: None)


def test_observer_startup_failure_is_exposed_and_stops_thread(monkeypatch):
    @contextmanager
    def connect(**kwargs):
        yield object()

    def failed(*args, **kwargs):
        raise OSError('database unavailable')

    monkeypatch.setattr(controller, 'conectar', connect)
    monkeypatch.setattr(controller, 'watch_round', failed)
    observer = controller.RecoveryObserver(lambda: True, 30)
    observer.target = METADATA.target
    with pytest.raises(controller.ScenarioError):
        observer.start(1)
    observer.stop()
    assert isinstance(observer.error, OSError)
    assert not observer.thread.is_alive()


def test_controller_cli_invalid_identity_never_connects(monkeypatch, tmp_path):
    monkeypatch.setattr(controller, 'get_settings', lambda: type('Settings', (), dict(
        target_ssh_host='192.0.2.152', target_ssh_user='polaris', target_ssh_key_path=str(tmp_path / 'service_key')))())
    monkeypatch.setattr(controller, 'runner_ssh', lambda *args: pytest.fail('must not create runner'))
    assert controller.main(['reset', '--run-id', '1', '--admin-user', 'polaris',
                            '--admin-key-file', str(tmp_path / 'key')]) == 2


@pytest.fixture
def shell_lab(tmp_path):
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('bash unavailable; real service script remains unvalidated')
    (tmp_path / 'id').write_text('#!/bin/sh\necho "${FAKE_UID:-0}"\n')
    (tmp_path / 'systemctl').write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$STATE_DIR/calls"
case "$1" in
is-active) cat "$STATE_DIR/state"; [ "$(cat "$STATE_DIR/state")" = active ];;
stop) echo inactive > "$STATE_DIR/state";;
start) echo active > "$STATE_DIR/state";;
*) exit 99;;
esac
''')
    for command in ('id', 'systemctl'):
        (tmp_path / command).chmod(0o700)
    (tmp_path / 'state').write_text('active\n')

    def run(action, state=None, uid='0'):
        if state:
            (tmp_path / 'state').write_text(state + '\n')
        env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ.get('PATH', ''),
                   STATE_DIR=str(tmp_path), FAKE_UID=uid)
        return subprocess.run([bash, str(controller.SCRIPT), action], env=env, capture_output=True, text=True)

    return run, tmp_path


def test_shell_injects_only_nginx_and_reset_requires_explicit_invocation(shell_lab):
    run, directory = shell_lab
    assert run('check').returncode == 0
    assert run('inject').stdout == 'nginx: inactive\n'
    assert (directory / 'state').read_text() == 'inactive\n'
    assert run('reset').stdout == 'nginx: active\n'
    assert (directory / 'calls').read_text().splitlines() == [
        'is-active nginx', 'is-active nginx', 'stop nginx', 'is-active nginx',
        'start nginx', 'is-active nginx']


def test_shell_refuses_unclean_unprivileged_and_unknown_actions(shell_lab):
    run, directory = shell_lab
    assert run('inject', state='inactive').returncode != 0
    assert run('inject', state='active', uid='1000').returncode != 0
    assert run('stop other').returncode == 2
    assert 'stop nginx' not in (directory / 'calls').read_text()


def test_reset_of_old_round_cannot_interfere_with_another_unassessed_round():
    connection, actions = Connection(row=round_row(resolvido=False)), []
    connection.open_runs = [{'id': 7}]
    with pytest.raises(controller.ScenarioError, match='another round'):
        controller.reset_round(connection, 1, METADATA.target, actions.append, lambda: True)
    assert actions == []


def test_failed_observer_arming_discards_uninjected_round():
    connection, actions = Connection(), []

    class FailedObserver(Observer):
        def start(self, run_id):
            raise controller.ScenarioError('cannot arm')

    with pytest.raises(InjectionFailed):
        controller.run_round(connection, METADATA, actions.append, lambda: True,
                             FailedObserver(actions), sleep=lambda _: None)
    assert 'inject' not in actions
    assert connection.row['descartada'] is True
    assert 'stop_observer' in actions


def test_observer_worker_records_using_dedicated_connection_and_runs_ready_hook(monkeypatch):
    sessions = []

    @contextmanager
    def connect(**kwargs):
        sessions.append(kwargs)
        yield object()

    def watch(connection, run_id, target, probe, timeout, **kwargs):
        assert run_id == 1 and target == METADATA.target
        kwargs['on_ready']()
        return START

    monkeypatch.setattr(controller, 'conectar', connect)
    monkeypatch.setattr(controller, 'watch_round', watch)
    observer = controller.RecoveryObserver(lambda: True, 30)
    observer.target = METADATA.target
    observer.start(1)
    assert observer.wait() == START
    observer.stop()
    assert sessions == [{'autocommit': True}]
    assert not observer.thread.is_alive()


def test_source_revision_refuses_tracked_changes_without_reading_credentials(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return type('Result', (), {'stdout': ' M src/engine/service.py'})()

    monkeypatch.setattr(controller.subprocess, 'run', run)
    with pytest.raises(controller.ScenarioError, match='commit tracked changes'):
        controller.repository_revision()
    assert calls[0][:4] == ['git', '-C', str(controller.ROOT), 'status']


def test_output_failure_does_not_discard_successfully_injected_evidence():
    connection, actions = Connection(), []

    def failed_output(message):
        raise BrokenPipeError()

    with pytest.raises(controller.ScenarioError, match='Round 1'):
        controller.run_round(connection, METADATA, actions.append, lambda: True,
                             Observer(actions), sleep=lambda _: None, emit=failed_output)
    assert connection.row['descartada'] is False
    assert 'inject' in actions
    assert 'reset' not in actions


def test_cleanup_error_preserves_id_of_failed_injection():
    connection, actions = Connection(), []

    class FailedObserver(Observer):
        def start(self, run_id):
            raise OSError()

        def stop(self):
            raise OSError()

    with pytest.raises(controller.ScenarioError, match='Round 1: observer cleanup'):
        controller.run_round(connection, METADATA, actions.append, lambda: True,
                             FailedObserver(actions), sleep=lambda _: None)
    assert connection.row['descartada'] is True
    assert 'reset' not in actions


@pytest.mark.parametrize('arm', ['baseline', 'hitl'])
def test_cli_run_emits_measurement_without_assessment_or_approval(monkeypatch, tmp_path, capsys, arm):
    settings = type('Settings', (), dict(target_ssh_host=METADATA.target,
        target_ssh_user='polaris', target_ssh_key_path=str(tmp_path / 'service_key'),
        scripts_path=tmp_path, rules_path=tmp_path, schema_path=tmp_path))()
    monkeypatch.setattr(controller, 'get_settings', lambda: settings)
    monkeypatch.setattr(controller, 'load_catalog', lambda _: object())
    monkeypatch.setattr(controller, 'load', lambda *args: type('KB', (), {'versao_kb': '1.0.1'})())
    monkeypatch.setattr(controller, 'repository_revision', lambda: METADATA.commit_sha)
    monkeypatch.setattr(controller, 'runner_ssh', lambda *args: lambda *args, **kwargs: None)

    @contextmanager
    def connect():
        yield object()

    def run(connection, metadata, *args, **kwargs):
        assert metadata == replace(METADATA, arm=arm)
        return 1, START

    monkeypatch.setattr(controller, 'conectar', connect)
    monkeypatch.setattr(controller, 'run_round', run)
    assert controller.main(['run', '--arm', arm, '--repetition', '1', '--operator', 'operator',
                            '--system-version', '0.4.0', '--timeout', '30', '--admin-user', 'administrator',
                            '--admin-key-file', str(tmp_path / 'admin_key')]) == 0
    assert 'recovery_measured' in capsys.readouterr().out


def test_explicit_source_sha_mismatch_aborts_before_database(monkeypatch, tmp_path):
    settings = type('Settings', (), dict(target_ssh_host=METADATA.target,
        target_ssh_user='polaris', target_ssh_key_path=str(tmp_path / 'service_key'),
        scripts_path=tmp_path, rules_path=tmp_path, schema_path=tmp_path))()
    monkeypatch.setattr(controller, 'get_settings', lambda: settings)
    monkeypatch.setattr(controller, 'load_catalog', lambda _: object())
    monkeypatch.setattr(controller, 'load', lambda *args: type('KB', (), {'versao_kb': '1.0.1'})())
    monkeypatch.setattr(controller, 'repository_revision', lambda: METADATA.commit_sha)
    monkeypatch.setattr(controller, 'runner_ssh', lambda *args: lambda *args, **kwargs: None)
    monkeypatch.setattr(controller, 'conectar', lambda: pytest.fail('must not connect'))
    assert controller.main(['run', '--arm', 'hitl', '--repetition', '1', '--operator', 'operator',
                            '--system-version', '0.4.0', '--timeout', '30', '--admin-user', 'administrator',
                            '--admin-key-file', str(tmp_path / 'admin_key'), '--commit-sha', 'b' * 40]) == 2


@pytest.mark.parametrize('with_sha', [True, False])
def test_image_without_git_requires_explicit_build_sha(monkeypatch, tmp_path, with_sha):
    settings = type('Settings', (), dict(target_ssh_host=METADATA.target,
        target_ssh_user='polaris', target_ssh_key_path=str(tmp_path / 'service_key'),
        scripts_path=tmp_path, rules_path=tmp_path, schema_path=tmp_path))()
    monkeypatch.setattr(controller, 'ROOT', tmp_path)
    monkeypatch.setattr(controller, 'get_settings', lambda: settings)
    monkeypatch.setattr(controller, 'load_catalog', lambda _: object())
    monkeypatch.setattr(controller, 'load', lambda *args: type('KB', (), {'versao_kb': '1.0.1'})())
    monkeypatch.setattr(controller, 'repository_revision', lambda: pytest.fail('image does not have Git'))
    monkeypatch.setattr(controller, 'runner_ssh', lambda *args: lambda *args, **kwargs: None)

    @contextmanager
    def connect():
        assert with_sha
        yield object()

    def run(connection, metadata, *args, **kwargs):
        assert metadata.commit_sha == METADATA.commit_sha
        return 1, START

    monkeypatch.setattr(controller, 'conectar', connect)
    monkeypatch.setattr(controller, 'run_round', run)
    arguments = ['run', '--arm', 'hitl', '--repetition', '1', '--operator', 'operator',
                 '--system-version', '0.4.0', '--timeout', '30', '--admin-user', 'administrator',
                 '--admin-key-file', str(tmp_path / 'admin_key')]
    if with_sha:
        arguments += ['--commit-sha', METADATA.commit_sha]
    assert controller.main(arguments) == (0 if with_sha else 2)
