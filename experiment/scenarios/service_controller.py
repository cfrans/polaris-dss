"""Operator-invoked R003 injection, independent observation and explicit post-round reset."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time

from experiment.rounds import InjectionFailed, RoundMetadata, locked_round, register_injection, require_idle
from experiment.verify.service_watcher import service_probe, watch_round
from src.db.connection import conectar
from src.engine.config import get_settings
from src.engine.knowledge_base import load
from src.engine.remediation import runner_ssh
from src.engine.script_catalog import load_catalog

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve().with_name('service_scenario.sh')
LOCK_NAMESPACE = 17017
SCENARIOS = {'service_down': 'R003', 'cpu_high': 'R002', 'disk_full': 'R001'}


class ScenarioError(RuntimeError):
    pass


@dataclass
class AdminTransport:
    runner: object
    use_sudo: bool = True

    def __call__(self, action: str) -> None:
        if action not in {'check', 'inject', 'reset'}:
            raise ValueError('unsupported scenario action')
        prefix = 'sudo -n ' if self.use_sudo else ''
        command = prefix + '/usr/bin/timeout -k 5s 20s /usr/bin/bash -s -- ' + action
        code, output, _ = self.runner(command, timeout=30, input_data=SCRIPT.read_bytes())
        expected = 'nginx: inactive' if action == 'inject' else 'nginx: active'
        if code != 0 or output.strip() != expected:
            raise ScenarioError(f'scenario {action} not confirmed (exit code {code})')


def validate_admin(user: str, key: Path, service_user: str, service_key: Path) -> None:
    if not user.strip() or user == service_user or key.resolve() == service_key.resolve():
        raise ValueError('use a separate administrative SSH user and key for instrumentation')


@contextmanager
def target_lock(connection, target: str):
    require_idle(connection)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(%s, hashtext(%s)) AS locked',
                           (LOCK_NAMESPACE, target))
            acquired = cursor.fetchone()['locked']
    if not acquired:
        raise ScenarioError('another controller owns this target')
    try:
        yield
    finally:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s, hashtext(%s)) AS unlocked',
                               (LOCK_NAMESPACE, target))


def check_environment(connection, target: str, probe) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM experiment_run WHERE host_alvo = %s '
                           'AND descartada = FALSE AND resolvido IS NULL', (target,))
            if cursor.fetchall():
                raise ScenarioError('an earlier round still needs assessment or discard')
            cursor.execute("SELECT id FROM audit_log WHERE regra_disparada IN ('R001','R002','R003') "
                           "AND status_execucao IN ('pendente', 'executando') "
                           'AND (hostname = %s OR host(ip_address) = %s)', (target, target))
            if cursor.fetchall():
                raise ScenarioError('an earlier incident is still open')
    if not probe():
        raise ScenarioError('target scenario is not healthy; restore and review the environment first')


class RecoveryObserver:
    """One dedicated PostgreSQL connection in the worker; caller never shares its connection."""
    def __init__(self, probe, timeout: float, *, watcher=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('observation timeout must be positive and finite')
        self.probe, self.timeout = probe, timeout
        self.watcher = watcher
        self.ready, self.cancel = Event(), Event()
        self.thread = None
        self.error, self.timestamp = None, None

    def start(self, run_id: int) -> None:
        if self.thread is not None:
            raise ScenarioError('observer cannot be started twice')

        def worker():
            try:
                with conectar(autocommit=True) as connection:
                    self.timestamp = (self.watcher or watch_round)(connection, run_id, self.target, self.probe,
                                                 self.timeout, on_ready=self.ready.set,
                                                 should_stop=self.cancel.is_set, sleep=self.cancel.wait)
            except BaseException as exc:
                self.error = exc
                self.ready.set()

        self.thread = Thread(target=worker, name=f'recovery-observer-{run_id}', daemon=True)
        self.thread.start()
        if not self.ready.wait(10) or self.error is not None:
            raise ScenarioError('observer could not be armed before injection')

    def wait(self):
        self.thread.join(self.timeout + 20)
        if self.thread.is_alive() or self.error is not None or self.timestamp is None:
            name = type(self.error).__name__ if self.error else 'unfinished observation'
            raise ScenarioError(f'observation incomplete ({name})')
        return self.timestamp

    def stop(self) -> None:
        self.cancel.set()
        if self.thread is not None:
            self.thread.join(15)
            if self.thread.is_alive():
                raise ScenarioError('observer did not stop; inspect the round before continuing')


def run_round(connection, metadata: RoundMetadata, admin_action, probe, observer,
              *, sleep=time.sleep, emit=lambda message: None, scenario="service_down"):
    metadata.validate()
    if scenario not in SCENARIOS or metadata.scenario != scenario:
        raise ValueError('round scenario does not match controller')
    with target_lock(connection, metadata.target):
        check_environment(connection, metadata.target, probe)
        admin_action('check')
        sleep(60)
        check_environment(connection, metadata.target, probe)
        admin_action('check')
        observer.target = metadata.target
        run_id = None
        try:
            def inject(committed_id):
                nonlocal run_id
                run_id = committed_id
                observer.start(committed_id)
                admin_action('inject')

            run_id = register_injection(connection, metadata, inject)
            emit({'event': 'injected', 'run_id': run_id, 'arm': metadata.arm})
            timestamp = observer.wait()
            return run_id, timestamp
        except InjectionFailed:
            raise
        except (Exception, KeyboardInterrupt) as exc:
            if run_id is not None:
                raise ScenarioError(f'Round {run_id}: observation incomplete ({type(exc).__name__}); '
                                    'assess a valid failure or discard invalid measurement; no automatic reset') from exc
            raise
        finally:
            try:
                observer.stop()
            except Exception as cleanup_error:
                raise ScenarioError(f'Round {run_id or "not registered"}: observer cleanup not confirmed '
                                    f'({type(cleanup_error).__name__}); inspect evidence and target') from cleanup_error


def reset_round(connection, run_id: int, target: str, admin_action, probe, *, scenario="service_down") -> None:
    if scenario not in SCENARIOS:
        raise ValueError("unsupported scenario")
    with target_lock(connection, target):
        with connection.transaction():
            with connection.cursor() as cursor:
                row = locked_round(cursor, run_id)
                if row['cenario'] != scenario or row['host_alvo'] != target:
                    raise ScenarioError('round scenario or target does not match')
                if not row['descartada'] and row['resolvido'] is None:
                    raise ScenarioError('assess or discard the round before resetting')
                cursor.execute('SELECT id FROM experiment_run WHERE host_alvo = %s AND id <> %s '
                               'AND descartada = FALSE AND resolvido IS NULL', (target, run_id))
                if cursor.fetchall():
                    raise ScenarioError('another round on this target still needs assessment or discard')
                cursor.execute('SELECT id FROM audit_log WHERE (experiment_run_id = %s '
                               'OR hostname = %s OR host(ip_address) = %s) '
                               "AND status_execucao IN ('pendente', 'executando')", (run_id, target, target))
                if cursor.fetchall():
                    raise ScenarioError('close the linked or target pending/executing incident before resetting')
        admin_action('reset')
        if not probe():
            raise ScenarioError('scenario recovery after reset not confirmed')


def repository_revision() -> str:
    status = subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=no'],
                            capture_output=True, text=True, check=True)
    if status.stdout.strip():
        raise ScenarioError('commit tracked changes before starting a round')
    revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, check=True)
    return revision.stdout.strip()


def main(argv: list[str] | None = None, *, scenario="service_down") -> int:
    if scenario not in SCENARIOS:
        raise ValueError("unsupported scenario")
    parser = argparse.ArgumentParser(description=f'Explicit {scenario} injection, observation and post-round reset')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--admin-user', required=True)
    common.add_argument('--admin-key-file', type=Path, required=True)
    sub = parser.add_subparsers(dest='action', required=True)
    run = sub.add_parser('run', parents=[common])
    run.add_argument('--arm', choices=('baseline', 'hitl'), required=True)
    run.add_argument('--repetition', type=int, required=True)
    run.add_argument('--operator', required=True)
    run.add_argument('--system-version', required=True, help='actual frozen release label')
    run.add_argument('--timeout', type=float, required=True)
    run.add_argument('--commit-sha', help='full build SHA, required when Git metadata is absent')
    reset = sub.add_parser('reset', parents=[common])
    reset.add_argument('--run-id', type=int, required=True)
    if scenario == 'disk_full':
        sub.add_parser('prepare', parents=[common], help='create the disposable gzip fixture before a round')
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        if not settings.target_ssh_host or not settings.target_ssh_key_path:
            raise ValueError('configure TARGET_SSH_HOST and TARGET_SSH_KEY_PATH')
        admin_key = args.admin_key_file if args.admin_key_file.is_absolute() else ROOT / args.admin_key_file
        service_key = Path(settings.target_ssh_key_path)
        service_key = service_key if service_key.is_absolute() else ROOT / service_key
        validate_admin(args.admin_user, admin_key, settings.target_ssh_user, service_key)
        catalog = load_catalog(settings.scripts_path)
        reader = runner_ssh(settings.target_ssh_host, settings.target_ssh_user, str(service_key))
        probe = lambda: service_probe(reader, catalog)
        admin = AdminTransport(runner_ssh(settings.target_ssh_host, args.admin_user, str(admin_key)),
                               use_sudo=args.admin_user != 'root')
        watcher = None
        if scenario != 'service_down':
            from functools import partial
            from experiment.scenarios.resource_controller import ResourceTransport
            from experiment.verify.resource_watcher import resource_probe, watch_resource_round
            probe = partial(resource_probe, reader, catalog, scenario)
            admin = ResourceTransport(runner_ssh(settings.target_ssh_host, args.admin_user, str(admin_key)),
                                      scenario, use_sudo=args.admin_user != 'root')
            watcher = partial(watch_resource_round, scenario=scenario)
        metadata, observer = None, None
        if args.action == 'run':
            if scenario == 'cpu_high' and (not math.isfinite(args.timeout) or not 0 < args.timeout <= 1800):
                raise ValueError('CPU observation limit must be at most 1800s, below the 3600s safety expiry')
            kb = load(settings.rules_path, settings.schema_path)
            revision = args.commit_sha
            if (ROOT / '.git').exists():
                actual_revision = repository_revision()
                if revision is not None and revision != actual_revision:
                    raise ValueError('declared SHA does not match the source checkout')
                revision = actual_revision
            elif revision is None:
                raise ValueError('provide the full build SHA when Git metadata is absent')
            metadata = RoundMetadata(scenario, args.arm, args.repetition, args.system_version,
                                     revision, kb.versao_kb, settings.target_ssh_host, args.operator)
            metadata.validate()
            observer = RecoveryObserver(probe, args.timeout, watcher=watcher)
        with conectar() as connection:
            if args.action == 'prepare':
                with target_lock(connection, settings.target_ssh_host):
                    check_environment(connection, settings.target_ssh_host, probe)
                    admin('prepare')
                print(json.dumps({'event': 'fixture_prepared', 'scenario': scenario}))
            elif args.action == 'reset':
                reset_round(connection, args.run_id, settings.target_ssh_host, admin, probe, scenario=scenario)
                print(json.dumps({'event': 'reset_confirmed', 'run_id': args.run_id}))
            else:
                emit = lambda message: print(json.dumps(message), flush=True)
                run_id, timestamp = run_round(connection, metadata, admin, probe, observer, emit=emit, scenario=scenario)
                emit({'event': 'recovery_measured', 'run_id': run_id, 'ts_verificado_ok': timestamp.isoformat()})
    except (Exception, KeyboardInterrupt) as exc:
        detail = str(exc) if isinstance(exc, (ScenarioError, ValueError)) or hasattr(exc, 'run_id') else type(exc).__name__
        print(f'Controller aborted: {detail}.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
