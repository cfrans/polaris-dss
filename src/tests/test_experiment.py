"""Offline measurement tests; these do not validate the laboratory transport."""
from datetime import datetime, timedelta, timezone
import csv

import pytest

from experiment.verify.service_watcher import (
    ObservationError, RoundStore, observe_recovery, service_probe, watch_round,
)
from experiment.analysis.consolidar import COLUMNS, export_csv, read_rounds
from src.engine.script_catalog import load_catalog
from src.engine.config import get_settings

START = datetime(2026, 10, 5, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.elapsed = 0.0
        self.samples = []

    def monotonic(self):
        return self.elapsed

    def sleep(self, duration):
        self.elapsed += duration

    def utc_now(self):
        return START + timedelta(seconds=self.elapsed)


def observe(states, timeout=20, duration=0):
    clock, recorded = Clock(), []
    states = iter(states)

    def probe():
        clock.samples.append(clock.elapsed)
        clock.elapsed += duration
        return next(states)

    result = observe_recovery(probe, clock.utc_now, recorded.append, timeout,
                              monotonic=clock.monotonic, sleep=clock.sleep)
    return result, recorded, clock


def test_first_healthy_sample_is_recorded_only_after_observed_failure_and_confirmation():
    result, recorded, clock = observe([True, True, False, True, True, True])
    assert result == START + timedelta(seconds=3)
    assert recorded == [result]
    assert clock.samples == [0, 1, 2, 3, 4, 5]


def test_oscillation_resets_the_confirmation_streak():
    result, recorded, _ = observe([False, True, True, False, True, True, True])
    assert result == START + timedelta(seconds=4)
    assert recorded == [result]


@pytest.mark.parametrize("healthy", [True, False])
def test_timeout_does_not_record_unobserved_or_unrecovered_failure(healthy):
    clock, recorded = Clock(), []
    with pytest.raises(ObservationError):
        observe_recovery(lambda: healthy, clock.utc_now, recorded.append, 3,
                         monotonic=clock.monotonic, sleep=clock.sleep)
    assert recorded == []
    assert clock.elapsed == 3


def test_transport_error_aborts_without_a_measurement():
    clock, recorded = Clock(), []

    def probe():
        raise OSError("SSH unavailable")

    with pytest.raises(OSError):
        observe_recovery(probe, clock.utc_now, recorded.append, 3,
                         monotonic=clock.monotonic, sleep=clock.sleep)
    assert recorded == []


def test_slow_checks_do_not_overlap_or_record_after_deadline():
    result, _, clock = observe([False, True, True, True], duration=1.5)
    assert clock.samples == [0, 1.5, 3, 4.5]
    assert result == START + timedelta(seconds=3)
    clock, recorded = Clock(), []

    def slow_probe():
        clock.elapsed += 4
        return False

    with pytest.raises(ObservationError):
        observe_recovery(slow_probe, clock.utc_now, recorded.append, 3,
                         monotonic=clock.monotonic, sleep=clock.sleep)
    assert recorded == []


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_timeout_must_be_positive_and_finite(timeout):
    with pytest.raises(ValueError):
        observe_recovery(lambda: True, lambda: START, lambda _: None, timeout)


@pytest.mark.parametrize("code,output,expected", [
    (0, "nginx: active\n", True), (1, "nginx: inactive\n", False),
    (1, "nginx: failed\n", False), (124, "", None),
    (0, "unexpected output", None), (1, "nginx: active", None),
])
def test_probe_uses_only_the_read_only_service_script(code, output, expected):
    calls = []

    def runner(command, timeout, input_data):
        calls.append((command, timeout, input_data))
        return code, output, ""

    catalog = load_catalog(get_settings().scripts_path)
    if expected is None:
        with pytest.raises(ObservationError):
            service_probe(runner, catalog)
    else:
        assert service_probe(runner, catalog) is expected
    command, timeout, data = calls[0]
    assert "sudo" not in command
    assert command.endswith("nginx")
    assert timeout == 10
    assert b"systemctl is-active" in data
    assert b"systemctl restart" not in data


class Connection:
    def __init__(self, row=None, locked=True, update=True):
        self.row = row or dict(cenario="service_down", braco="baseline", descartada=False,
                              ts_injecao=START, ts_verificado_ok=None, host_alvo="target")
        self.locked, self.update = locked, update
        self.calls = []
        self.result = None

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=None):
        self.calls.append((sql, args))
        if "pg_try_advisory_lock" in sql:
            self.result = {"locked": self.locked}
        elif "clock_timestamp" in sql:
            self.result = {"sampled_at": START + timedelta(seconds=10)}
        elif sql.startswith("UPDATE"):
            self.result = {"id": 1} if self.update else None
        else:
            self.result = self.row

    def fetchone(self):
        return self.result

    def fetchall(self):
        return [self.row]


def test_store_updates_only_t5_and_releases_the_lock():
    connection = Connection()
    clock = Clock()
    states = iter([False, True, True, True])
    watch_round(connection, 1, "target", lambda: next(states), 10,
                monotonic=clock.monotonic, sleep=clock.sleep)
    updates = [(sql, args) for sql, args in connection.calls if sql.startswith("UPDATE")]
    assert len(updates) == 1
    sql, args = updates[0]
    assert "SET ts_verificado_ok = %s WHERE" in sql
    assert "descartada = FALSE AND ts_verificado_ok IS NULL AND resolvido IS NULL" in sql
    assert args == (START + timedelta(seconds=10), 1, "target", "service_down")
    assert not any("audit_log" in sql for sql, _ in connection.calls)
    assert "pg_advisory_unlock" in connection.calls[-1][0]


@pytest.mark.parametrize("changes", [
    {"cenario": "disk_full"}, {"braco": "invalid"}, {"descartada": True},
    {"ts_verificado_ok": START}, {"resolvido": False}, {"host_alvo": "other"},
    {"ts_injecao": START + timedelta(days=1)}, {"ts_injecao": START.replace(tzinfo=None)},
])
def test_store_refuses_invalid_rounds_and_unlocks(changes):
    connection = Connection()
    connection.row.update(changes)
    with pytest.raises(ObservationError):
        watch_round(connection, 1, "target", lambda: pytest.fail("must not probe"), 10)
    assert not any(sql.startswith("UPDATE") for sql, _ in connection.calls)
    assert "pg_advisory_unlock" in connection.calls[-1][0]


def test_duplicate_observer_never_unlocks_another_observer():
    connection = Connection(locked=False)
    with pytest.raises(ObservationError):
        watch_round(connection, 1, "target", lambda: True, 10)
    assert len(connection.calls) == 1


def test_changed_round_cannot_be_overwritten():
    connection = Connection(update=False)
    store = RoundStore(connection, 1)
    store.claim("target")
    with pytest.raises(ObservationError):
        store.record(START + timedelta(seconds=20))
    store.release()


def csv_round(**changes):
    row = dict.fromkeys(COLUMNS)
    row.update(id=1, cenario="service_down", braco="baseline", rodada=1,
               descartada=False, ts_injecao=START,
               ts_verificado_ok=START + timedelta(seconds=2.75),
               comandos_usados="systemctl status nginx\nsystemctl restart nginx")
    row.update(changes)
    return row


def test_export_preserves_incomplete_discarded_rounds_and_literal_commands(tmp_path):
    output = tmp_path / "rounds.csv"
    assert export_csv([csv_round(), csv_round(id=2, descartada=True, ts_verificado_ok=None)], output) == 2
    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["mttr_segundos"] == "2.75"
    assert rows[0]["comandos_usados"] == csv_round()["comandos_usados"]
    assert rows[1]["mttr_segundos"] == ""
    assert rows[1]["resolvido"] == ""
    assert rows[1]["descartada"] == "True"
    assert rows[0]["ts_injecao"].endswith("+00:00")


@pytest.mark.parametrize("changes", [
    {"ts_injecao": None}, {"ts_injecao": START.replace(tzinfo=None)},
    {"ts_verificado_ok": START - timedelta(seconds=1)},
])
def test_invalid_timestamps_do_not_leave_a_partial_export(tmp_path, changes):
    output = tmp_path / "rounds.csv"
    with pytest.raises(ValueError):
        export_csv([csv_round(), csv_round(**changes)], output)
    assert not output.exists()


def test_export_never_replaces_existing_evidence(tmp_path):
    output = tmp_path / "rounds.csv"
    output.write_text("previous evidence")
    with pytest.raises(FileExistsError):
        export_csv([csv_round()], output)
    assert output.read_text() == "previous evidence"


def test_empty_export_has_headers_and_query_keeps_all_rounds(tmp_path):
    output = tmp_path / "empty.csv"
    assert export_csv([], output) == 0
    assert output.read_text().startswith("id,cenario,braco,")
    connection = Connection()
    assert read_rounds(connection) == [connection.row]
    sql, args = connection.calls[0]
    assert sql.startswith("SELECT ") and "WHERE" not in sql
    assert args is None


def test_ready_hook_precedes_first_probe_and_cancellation_never_records_t5():
    connection, clock, events = Connection(), Clock(), []
    states = iter([False, True, True, True])

    def probe():
        events.append('probe')
        return next(states)

    watch_round(connection, 1, 'target', probe, 10,
                on_ready=lambda: events.append('ready'),
                monotonic=clock.monotonic, sleep=clock.sleep)
    assert events[0] == 'ready'

    clock, recorded = Clock(), []
    cancelled = False
    count = 0

    def cancelled_probe():
        nonlocal count, cancelled
        count += 1
        if count == 4:
            cancelled = True
        return count > 1

    with pytest.raises(ObservationError, match='cancelled'):
        observe_recovery(cancelled_probe, clock.utc_now, recorded.append, 10,
                         should_stop=lambda: cancelled,
                         monotonic=clock.monotonic, sleep=clock.sleep)
    assert recorded == []
