"""Global experiment guards; no real SSH, service actions or data deletion."""
from pathlib import Path
import subprocess

import pytest

from experiment.scenarios import reset_environment as reset
from experiment.scenarios.service_controller import ScenarioError
from src.tests.test_rounds import START, round_row
from src.tests.test_service_controller import Connection as BaseConnection
from src.tests.test_resource_scenarios import resource_shell

SCENARIOS = ('service_down', 'cpu_high', 'disk_full')


class Connection(BaseConnection):
    def __init__(self):
        super().__init__(row=round_row(host_alvo='target', braco='baseline'))



def checks(events, unhealthy=None):
    probes = {s: (lambda s=s: s != unhealthy) for s in SCENARIOS}
    admins = {s: (lambda action, s=s: events.append((s, action))) for s in SCENARIOS}
    return probes, admins


def test_global_check_inspects_every_scenario_twice_without_mutating_database():
    connection, events = Connection(), []
    probes, admins = checks(events)
    result = reset.check_global(connection, 'target', probes, admins,
                                sleep=lambda seconds: events.append(seconds))
    assert result['automatic_checks_passed'] is True
    assert result['manual_checks_required']
    assert events == [('service_down', 'check'), ('cpu_high', 'check'), ('disk_full', 'check-clean'), 60,
                      ('service_down', 'check'), ('cpu_high', 'check'), ('disk_full', 'check-clean')]
    assert not any(sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')) for sql, _ in connection.calls)


@pytest.mark.parametrize('scenario', SCENARIOS)
def test_any_unhealthy_scenario_aborts_without_reset_or_injection(scenario):
    connection, events = Connection(), []
    probes, admins = checks(events, unhealthy=scenario)
    with pytest.raises(ScenarioError):
        reset.check_global(connection, 'target', probes, admins, sleep=lambda _: None)
    assert all(action not in ('reset', 'inject', 'prepare') for _, action in events)


@pytest.mark.parametrize('dirty', ['round', 'incident', 'lock'])
def test_database_guards_precede_remote_checks(dirty):
    connection, events = Connection(), []
    if dirty == 'round':
        connection.open_runs = [{'id': 10}]
    if dirty == 'incident':
        connection.open_incidents = [{'id': 10}]
    if dirty == 'lock':
        connection.target_locked = False
    probes, admins = checks(events)
    with pytest.raises(ScenarioError):
        reset.check_global(connection, 'target', probes, admins, sleep=lambda _: None)
    assert not events


def test_disk_round_requires_prepared_fixture_but_other_rounds_require_clean_mount():
    events = []
    probes, admins = checks(events)
    reset.check_global(Connection(), 'target', probes, admins, scenario='disk_full', sleep=lambda _: None)
    assert ('disk_full', 'check') in events
    assert ('disk_full', 'check-clean') not in events


def test_explicit_reset_routes_only_the_assessed_round_then_checks_all():
    connection, events = Connection(), []
    connection.row['resolvido'] = False
    probes, admins = checks(events)
    result = reset.reset_global(connection, 1, 'target', probes, admins, sleep=lambda _: None)
    assert result['reset_run_id'] == 1
    assert events.count(('service_down', 'reset')) == 1
    assert not any(action in ('inject', 'prepare') for _, action in events)
    assert ('cpu_high', 'reset') not in events and ('disk_full', 'reset') not in events
    assert not any(sql.startswith(('INSERT', 'UPDATE', 'DELETE')) for sql, _ in connection.calls)


def test_unassessed_round_never_reaches_reset():
    connection, events = Connection(), []
    probes, admins = checks(events)
    with pytest.raises(ScenarioError):
        reset.reset_global(connection, 1, 'target', probes, admins, sleep=lambda _: None)
    assert not events


def test_dirty_other_scenario_after_explicit_reset_is_reported_without_repair():
    connection, events = Connection(), []
    connection.row['resolvido'] = False
    probes, admins = checks(events, unhealthy='cpu_high')
    with pytest.raises(ScenarioError, match='reset sent'):
        reset.reset_global(connection, 1, 'target', probes, admins, sleep=lambda _: None)
    assert events[0] == ('service_down', 'reset')
    assert ('cpu_high', 'reset') not in events


def test_read_only_disk_clean_branch_accepts_empty_fixture_and_rejects_leftovers():
    script = (Path(__file__).resolve().parents[2] / 'experiment/scenarios/disk_scenario.sh').read_text()
    assert 'check-clean' in script
    # Execute the actual new branch with a shell function that poisons destructive commands.
    branch = script.split('if [[ "$action" == check-clean ]]; then', 1)[1].split('\nfi', 1)[0]
    prelude = 'set -euo pipefail; archive=/nonexistent-fixture-a; filler=/nonexistent-fixture-b; manifest=/nonexistent-fixture-c; usage(){ echo 0; }; rm(){ exit 99; }; dd(){ exit 99; }; fallocate(){ exit 99; };'
    result = subprocess.run(['bash', '-c', prelude + branch], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == 'disk: clean'


def test_real_database_pending_round_blocks_global_checks(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO experiment_run (cenario, braco, rodada, host_alvo, ts_injecao) "
                    "VALUES ('service_down','baseline',1,'target',%s)", (START,))
    conn.commit()
    events = []
    probes, admins = checks(events)
    with pytest.raises(ScenarioError, match='earlier round'):
        reset.check_global(conn, 'target', probes, admins, sleep=lambda _: None)
    assert not events
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(17017, hashtext('target')) AS locked")
        assert cur.fetchone()['locked'] is True
        cur.execute("SELECT pg_advisory_unlock(17017, hashtext('target'))")
    conn.rollback()


def test_disk_clean_inspection_preserves_fixture_and_accepts_only_empty_mount(resource_shell):
    run, mount, _, _ = resource_shell
    before = {p.name: (p.stat().st_ino, p.stat().st_size) for p in mount.iterdir()}
    assert run('disk_full', 'check-clean').returncode != 0
    assert {p.name: (p.stat().st_ino, p.stat().st_size) for p in mount.iterdir()} == before
    assert run('disk_full', 'reset').returncode == 0
    assert run('disk_full', 'check-clean').stdout.strip() == 'disk: clean'
    foreign = mount / 'foreign.log'
    foreign.write_text('preserve')
    assert run('disk_full', 'check-clean').returncode != 0
    assert foreign.read_text() == 'preserve'


def test_disk_clean_transport_accepts_only_known_read_only_marker():
    from experiment.scenarios.resource_controller import ResourceTransport
    events = []
    def runner(command, **kwargs):
        events.append(command)
        return 0, 'disk: clean', ''
    ResourceTransport(runner, 'disk_full')('check-clean')
    assert events[0].endswith('bash -s -- check-clean')
    with pytest.raises(ValueError):
        ResourceTransport(runner, 'cpu_high')('check-clean')
    assert len(events) == 1


def test_global_reset_holds_lock_during_external_action_and_all_checks(conn):
    from src.db.connection import conectar
    with conn.cursor() as cur:
        cur.execute("INSERT INTO experiment_run (cenario, braco, rodada, host_alvo, ts_injecao, resolvido) "
                    "VALUES ('service_down','baseline',1,'target',%s,FALSE) RETURNING id", (START,))
        run_id = cur.fetchone()['id']
    conn.commit()
    events = []
    probes, admins = checks(events)
    def action(operation):
        with conectar() as other:
            with pytest.raises(ScenarioError, match='another controller'):
                reset.check_global(other, 'target', probes, admins, sleep=lambda _: None)
        events.append(('service_down', operation))
    admins['service_down'] = action
    result = reset.reset_global(conn, run_id, 'target', probes, admins, sleep=lambda _: None)
    assert result['reset_run_id'] == run_id
    with conn.cursor() as cur:
        cur.execute('SELECT resolvido, ts_verificado_ok FROM experiment_run WHERE id=%s', (run_id,))
        assert cur.fetchone() == dict(resolvido=False, ts_verificado_ok=None)
    conn.rollback()
