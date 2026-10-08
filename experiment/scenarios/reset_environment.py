"""Read-only global preflight and explicit, round-scoped administrative reset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from experiment.rounds import locked_round
from experiment.scenarios.resource_controller import ResourceTransport
from experiment.scenarios.service_controller import (
    AdminTransport, ROOT, SCENARIOS, ScenarioError, check_environment, reset_round,
    target_lock, validate_admin,
)
from experiment.verify.resource_watcher import resource_probe
from experiment.verify.service_watcher import service_probe
from src.db.connection import conectar
from src.engine.config import get_settings
from src.engine.remediation import runner_ssh
from src.engine.script_catalog import load_catalog

MANUAL_CHECKS = (
    'Confirm NTP/skew on controller, Zabbix and target.',
    'Confirm prior Zabbix problems closed and triggers rearmed, without duplicates.',
    'Wait at least five minutes between rounds; the two samples do not prove this interval.',
    'Confirm frozen SHA/image/KB, round order and identical monitoring intervals.',
    'Save round evidence and inspect unrelated services/files for collateral effects.',
)


def inspect_all(connection, target, probes, admins, scenario):
    check_environment(connection, target, lambda: True)
    for name in SCENARIOS:
        action = 'check-clean' if name == 'disk_full' and scenario != 'disk_full' else 'check'
        admins[name](action)
        if probes[name]() is not True:
            raise ScenarioError(f'{name} is not healthy; inspect the target without automatic repair')


def check_under_lock(connection, target, probes, admins, scenario, sleep):
    if scenario is not None and scenario not in SCENARIOS:
        raise ValueError('unsupported next scenario')
    if set(probes) != set(SCENARIOS) or set(admins) != set(SCENARIOS):
        raise ValueError('all three scenarios must be inspected')
    inspect_all(connection, target, probes, admins, scenario)
    sleep(60)
    inspect_all(connection, target, probes, admins, scenario)
    return dict(automatic_checks_passed=True, target=target, next_scenario=scenario,
                manual_checks_required=list(MANUAL_CHECKS))


def check_global(connection, target, probes, admins, *, scenario=None, sleep=time.sleep):
    with target_lock(connection, target):
        return check_under_lock(connection, target, probes, admins, scenario, sleep)


def reset_global(connection, run_id, target, probes, admins, *, sleep=time.sleep):
    if type(run_id) is not int or run_id <= 0:
        raise ValueError('positive round ID required')
    if set(probes) != set(SCENARIOS) or set(admins) != set(SCENARIOS):
        raise ValueError('all three scenarios must be inspected')
    with target_lock(connection, target):
        with connection.transaction():
            with connection.cursor() as cursor:
                row = locked_round(cursor, run_id)
                scenario = row['cenario']
                if scenario not in SCENARIOS or row['host_alvo'] != target:
                    raise ScenarioError('round scenario or target does not match')
        # Locks de sessão são reentrantes; o lock externo permanece até concluir a inspeção.
        reset_round(connection, run_id, target, admins[scenario], probes[scenario], scenario=scenario)
        try:
            result = check_under_lock(connection, target, probes, admins, None, sleep)
        except Exception as exc:
            raise ScenarioError(f'Round {run_id}: reset sent; global confirmation failed '
                                f'({type(exc).__name__}); inspect other scenarios, no further reset performed') from exc
    result['reset_run_id'] = run_id
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='inspect only; never repair or prepare')
    action.add_argument('--reset-run-id', type=int, help='explicit reset of the assessed/discarded round only')
    parser.add_argument('--scenario', choices=tuple(SCENARIOS), help='next scenario; disk requires prepared fixture')
    parser.add_argument('--admin-user', required=True)
    parser.add_argument('--admin-key-file', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.reset_run_id is not None and args.scenario is not None:
            raise ValueError('post-round reset requires a clean fixture; do not pass --scenario')
        settings = get_settings()
        if not settings.target_ssh_host or not settings.target_ssh_key_path:
            raise ValueError('configure TARGET_SSH_HOST and TARGET_SSH_KEY_PATH')
        key = args.admin_key_file if args.admin_key_file.is_absolute() else ROOT / args.admin_key_file
        service_key = Path(settings.target_ssh_key_path)
        service_key = service_key if service_key.is_absolute() else ROOT / service_key
        validate_admin(args.admin_user, key, settings.target_ssh_user, service_key)
        catalog = load_catalog(settings.scripts_path)
        reader = runner_ssh(settings.target_ssh_host, settings.target_ssh_user, str(service_key))
        writer = runner_ssh(settings.target_ssh_host, args.admin_user, str(key))
        probes = {'service_down': lambda: service_probe(reader, catalog)}
        probes.update({name: (lambda name=name: resource_probe(reader, catalog, name))
                       for name in ('cpu_high', 'disk_full')})
        admins = {'service_down': AdminTransport(writer, use_sudo=args.admin_user != 'root')}
        admins.update({name: ResourceTransport(writer, name, use_sudo=args.admin_user != 'root')
                       for name in ('cpu_high', 'disk_full')})
        with conectar() as connection:
            if args.check:
                result = check_global(connection, settings.target_ssh_host, probes, admins, scenario=args.scenario)
            else:
                result = reset_global(connection, args.reset_run_id, settings.target_ssh_host, probes, admins)
        print(json.dumps(result))
    except (Exception, KeyboardInterrupt) as exc:
        detail = str(exc) if isinstance(exc, (ScenarioError, ValueError)) else type(exc).__name__
        print(f'Global environment check/reset aborted: {detail}.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
