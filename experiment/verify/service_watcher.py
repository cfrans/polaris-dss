"""Observe an existing R003 round without executing remediation.

Run from the repository root: python -m experiment.verify.service_watcher --help
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from typing import Callable

from src.db.connection import conectar
from src.engine.config import get_settings
from src.engine.remediation import prepare_command, runner_ssh
from src.engine.script_catalog import load_catalog


class ObservationError(RuntimeError):
    pass


def observe_recovery(
    probe: Callable[[], bool],
    utc_now: Callable[[], datetime],
    record: Callable[[datetime], None],
    timeout_seconds: float,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> datetime:
    """Record the first healthy sample confirmed by three consecutive successes.

    Initial healthy samples are ignored until an unhealthy sample was observed.
    Transport errors must raise instead of being converted to unhealthy samples.
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("observation timeout must be positive")
    deadline = monotonic() + timeout_seconds
    failure_seen = False
    consecutive = 0
    first_healthy = None
    while monotonic() < deadline:
        sample_started = monotonic()
        healthy = probe()
        sampled_at = utc_now()
        if monotonic() >= deadline:
            break
        if not healthy:
            failure_seen = True
            consecutive = 0
            first_healthy = None
        elif failure_seen:
            if consecutive == 0:
                first_healthy = sampled_at
            consecutive += 1
            if consecutive == 3:
                record(first_healthy)
                return first_healthy
        delay = max(0.0, sample_started + 1.0 - monotonic())
        sleep(min(delay, max(0.0, deadline - monotonic())))
    raise ObservationError("no observed failure followed by three healthy samples before timeout")


def service_probe(runner, catalog) -> bool:
    command, data = prepare_command("verify_service.sh nginx", catalog, 5, with_sudo=False)
    code, output, _ = runner(command, timeout=10, input_data=data)
    state = output.strip()
    if code == 0 and state == "nginx: active":
        return True
    if code == 1 and state in {
        "nginx: inactive", "nginx: failed", "nginx: activating",
        "nginx: deactivating", "nginx: reloading",
    }:
        return False
    raise ObservationError(f"service verification failed (exit code {code})")


class RoundStore:
    """Persist only the measurement, leaving correctness and manual fields untouched."""

    def __init__(self, connection, run_id: int):
        if run_id <= 0:
            raise ValueError("run ID must be positive")
        self.connection = connection
        self.run_id = run_id
        self.claimed = False

    def claim(self, target: str) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s) AS locked", (-self.run_id,))
            self.claimed = cursor.fetchone()["locked"]
            if not self.claimed:
                raise ObservationError("another observer owns this round")
            cursor.execute(
                "SELECT cenario, braco, descartada, ts_injecao, ts_verificado_ok, host_alvo "
                "FROM experiment_run WHERE id = %s", (self.run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise ObservationError("round does not exist")
        if row["cenario"] != "service_down" or row["braco"] not in {"baseline", "hitl"}:
            raise ObservationError("observer requires a service_down baseline or hitl round")
        if row["descartada"] or row["ts_verificado_ok"] is not None:
            raise ObservationError("round is discarded or already measured")
        if not target or row["host_alvo"] != target:
            raise ObservationError("round target differs from the configured SSH host")
        self.target = target
        self.started_at = row["ts_injecao"]
        if self.started_at is None or self.started_at.utcoffset() is None:
            raise ObservationError("round injection timestamp must include a timezone")
        if self.utc_now() < self.started_at:
            raise ObservationError("round injection timestamp is in the future")

    def utc_now(self) -> datetime:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT clock_timestamp() AS sampled_at")
            return cursor.fetchone()["sampled_at"]

    def record(self, timestamp: datetime) -> None:
        if not self.claimed or timestamp.utcoffset() is None or timestamp < self.started_at:
            raise ObservationError("invalid observation timestamp or unclaimed round")
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE experiment_run SET ts_verificado_ok = %s "
                "WHERE id = %s AND descartada = FALSE AND ts_verificado_ok IS NULL "
                "AND cenario = 'service_down' AND host_alvo = %s RETURNING id",
                (timestamp, self.run_id, self.target),
            )
            if cursor.fetchone() is None:
                raise ObservationError("round was discarded or measured by another process")

    def release(self) -> None:
        if self.claimed:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (-self.run_id,))
            self.claimed = False


def watch_round(connection, run_id: int, target: str, probe, timeout_seconds: float,
                *, monotonic=time.monotonic, sleep=time.sleep) -> datetime:
    store = RoundStore(connection, run_id)
    try:
        store.claim(target)
        return observe_recovery(probe, store.utc_now, store.record, timeout_seconds,
                                monotonic=monotonic, sleep=sleep)
    finally:
        store.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--timeout", type=float, required=True,
                        help="maximum observation duration in seconds; not remediation timeout")
    args = parser.parse_args(argv)
    if args.run_id <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("run ID and observation timeout must be positive")
    settings = get_settings()
    if not settings.target_ssh_host or not settings.target_ssh_key_path:
        parser.error("configure TARGET_SSH_HOST and TARGET_SSH_KEY_PATH")
    runner = runner_ssh(settings.target_ssh_host, settings.target_ssh_user,
                        settings.target_ssh_key_path)
    catalog = load_catalog(settings.scripts_path)
    try:
        with conectar(autocommit=True) as connection:
            timestamp = watch_round(connection, args.run_id, settings.target_ssh_host,
                                    lambda: service_probe(runner, catalog), args.timeout)
    except Exception as exc:
        print(f"Observation aborted ({type(exc).__name__}); no success is inferred.", file=sys.stderr)
        return 2
    print(json.dumps({"run_id": args.run_id, "ts_verificado_ok": timestamp.isoformat()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
