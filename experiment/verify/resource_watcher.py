"""Independent disk/CPU observation using the same criteria in both experimental arms."""
from __future__ import annotations

import re
import time

from experiment.verify.service_watcher import ObservationError, RoundStore, observe_recovery
from src.engine.remediation import prepare_command

SCENARIOS = {
    'disk_full': ('verify_disk.sh /mnt/polaris_test', r'uso de /mnt/polaris_test: (\d+)% \(limite 85%\)', 85, 0),
    'cpu_high': ('verify_cpu.sh', r'uso de CPU: (\d+)% \(limite 70%\)', 70, 30),
}


def resource_probe(runner, catalog, scenario: str) -> bool:
    if scenario not in SCENARIOS:
        raise ValueError('unsupported resource scenario')
    script, pattern, limit, _ = SCENARIOS[scenario]
    command, data = prepare_command(script, catalog, 5, with_sudo=False)
    code, output, _ = runner(command, timeout=10, input_data=data)
    match = re.fullmatch(pattern, output.strip())
    if match is None or not 0 <= int(match[1]) <= 100:
        raise ObservationError('invalid resource verification response')
    healthy = int(match[1]) < limit
    if code != (0 if healthy else 1):
        raise ObservationError(f'resource verification failed (exit code {code})')
    return healthy


def watch_resource_round(connection, run_id: int, target: str, probe, timeout_seconds: float,
                         *, scenario: str, monotonic=time.monotonic, sleep=time.sleep,
                         on_ready=lambda: None, should_stop=lambda: False):
    if scenario not in SCENARIOS:
        raise ValueError('unsupported resource scenario')
    store = RoundStore(connection, run_id, scenario)
    try:
        store.claim(target)
        on_ready()
        return observe_recovery(probe, store.utc_now, store.record, timeout_seconds,
                                monotonic=monotonic, sleep=sleep, should_stop=should_stop,
                                healthy_duration=SCENARIOS[scenario][3])
    finally:
        store.release()
