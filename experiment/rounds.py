"""Register injection, link explicit events and record human assessments.

No remediation, approval or remote command is implemented in this module.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from psycopg.pq import TransactionStatus
from src.db.connection import conectar

EXPECTED_RULES = {"disk_full": "R001", "cpu_high": "R002", "service_down": "R003"}
MANUAL_FIELDS = ("passos_manuais", "comandos_usados", "resolvido", "observacoes")
ROOT = Path(__file__).resolve().parents[1]


class RoundError(RuntimeError):
    pass


class InjectionFailed(RoundError):
    def __init__(self, run_id: int, message: str):
        self.run_id = run_id
        super().__init__(f"Round {run_id}: {message}")


def require_idle(connection) -> None:
    # Use a dedicated connection: never commit an unrelated caller transaction.
    if connection.autocommit or connection.info.transaction_status != TransactionStatus.IDLE:
        raise RoundError("a dedicated idle connection without autocommit is required")


def require_text(value, field: str, maximum: int | None = None, *, empty=False) -> None:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f"{field} must be text and cannot be blank")
    if "\x00" in value or (maximum is not None and len(value) > maximum):
        raise ValueError(f"{field} contains invalid characters or exceeds its limit")


@dataclass(frozen=True)
class RoundMetadata:
    scenario: str
    arm: str
    repetition: int
    system_version: str
    commit_sha: str
    kb_version: str
    target: str
    operator: str

    def validate(self) -> None:
        if self.scenario not in EXPECTED_RULES or self.arm not in {"baseline", "hitl"}:
            raise ValueError("invalid scenario or arm")
        if type(self.repetition) is not int or not 1 <= self.repetition <= 32767:
            raise ValueError("repetition must be a positive smallint")
        if not isinstance(self.commit_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", self.commit_sha):
            raise ValueError("commit SHA must contain 40 lowercase hexadecimal characters")
        for field, maximum in (("system_version", 32), ("kb_version", 16), ("target", 128), ("operator", 64)):
            require_text(getattr(self, field), field, maximum)


@dataclass(frozen=True)
class Assessment:
    manual_steps: int
    commands: str
    resolved: bool
    observations: str

    def validate(self) -> None:
        if type(self.manual_steps) is not int or not 0 <= self.manual_steps <= 32767:
            raise ValueError("manual steps must be a nonnegative smallint")
        if type(self.resolved) is not bool:
            raise ValueError("resolved must be an explicit boolean")
        require_text(self.commands, "commands", empty=True)
        require_text(self.observations, "observations")


def register_injection(connection, metadata: RoundMetadata, inject: Callable[[int], None]) -> int:
    """Persist t0 before invoking a controller's authorized injection callback.

    The callback receives the committed run ID, injects only the declared scenario,
    raises on failure and returns None.
    Transport and clean-environment checks belong to the injection controller.
    """
    metadata.validate()
    if not callable(inject):
        raise ValueError("an injection callback is required")
    require_idle(connection)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO experiment_run (cenario, braco, rodada, ts_injecao, versao_sistema, "
                "commit_sha, versao_kb, host_alvo, operador) "
                "VALUES (%s, %s, %s, clock_timestamp(), %s, %s, %s, %s, %s) RETURNING id",
                (metadata.scenario, metadata.arm, metadata.repetition, metadata.system_version,
                 metadata.commit_sha, metadata.kb_version, metadata.target, metadata.operator),
            )
            run_id = cursor.fetchone()["id"]
    # The context above has committed; a failed insert/commit cannot reach injection.
    try:
        if inject(run_id) is not None:
            raise RoundError("injection callback must return None on success")
    except (Exception, KeyboardInterrupt, SystemExit) as exc:
        reason = f"injection callback failed ({type(exc).__name__}); check the target before retrying"
        try:
            discard_round(connection, run_id, reason)
        except Exception as discard_error:
            raise InjectionFailed(run_id, "injection failed; discard was not persisted") from discard_error
        raise InjectionFailed(run_id, reason) from exc
    return run_id


def locked_round(cursor, run_id: int) -> dict:
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run ID must be positive")
    cursor.execute("SELECT * FROM experiment_run WHERE id = %s FOR UPDATE", (run_id,))
    row = cursor.fetchone()
    if row is None:
        raise RoundError("round does not exist")
    return row


def require_open(row: dict) -> None:
    if row["descartada"] or any(row[field] is not None for field in MANUAL_FIELDS):
        raise RoundError("round is discarded or already assessed")


def timestamps_match(row: dict, incident: dict, now: datetime) -> bool:
    start, end = row["ts_injecao"], row["ts_verificado_ok"] or now
    detected, created = incident["ts_deteccao"], incident["ts_criacao"]
    values = (start, end, detected, created, now)
    if any(not isinstance(value, datetime) or value.utcoffset() is None for value in values):
        return False
    return start <= detected <= created <= end <= now


def target_matches(target: str, incident: dict) -> bool:
    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        return target == incident["hostname"]
    try:
        return address == ipaddress.ip_address(str(incident["ip_address"]))
    except ValueError:
        return False


def link_incident(connection, run_id: int, incident_id: int, event_id: str) -> bool:
    """Return whether the linked rule matches; a mismatch remains evidence, not success."""
    if type(incident_id) is not int or incident_id <= 0:
        raise ValueError("incident ID must be positive")
    require_text(event_id, "event ID", 64)
    require_idle(connection)
    with connection.transaction():
        with connection.cursor() as cursor:
            row = locked_round(cursor, run_id)
            require_open(row)
            if row["braco"] != "hitl":
                raise RoundError("baseline rounds cannot link Polaris incidents")
            cursor.execute("SELECT * FROM audit_log WHERE id = %s FOR UPDATE", (incident_id,))
            incident = cursor.fetchone()
            if incident is None or incident["id_evento"] != event_id:
                raise RoundError("incident or explicit event ID does not match")
            cursor.execute("SELECT clock_timestamp() AS now")
            now = cursor.fetchone()["now"]
            if not target_matches(row["host_alvo"], incident) or not timestamps_match(row, incident, now):
                raise RoundError("target or incident timestamps are incompatible with the round")
            if incident["versao_kb"] != row["versao_kb"]:
                raise RoundError("incident knowledge-base version differs from the round")
            if incident["experiment_run_id"] not in (None, run_id):
                raise RoundError("incident already belongs to another round")
            cursor.execute("SELECT id FROM audit_log WHERE experiment_run_id = %s", (run_id,))
            linked = cursor.fetchall()
            if any(item["id"] != incident_id for item in linked):
                raise RoundError("round already has another incident")
            if incident["experiment_run_id"] is None:
                cursor.execute(
                    "UPDATE audit_log SET experiment_run_id = %s "
                    "WHERE id = %s AND experiment_run_id IS NULL RETURNING id", (run_id, incident_id),
                )
                if cursor.fetchone() is None:
                    raise RoundError("incident link changed concurrently")
            return incident["regra_disparada"] == EXPECTED_RULES[row["cenario"]]


def assess_round(connection, run_id: int, assessment: Assessment) -> None:
    assessment.validate()
    require_idle(connection)
    with connection.transaction():
        with connection.cursor() as cursor:
            row = locked_round(cursor, run_id)
            require_open(row)
            if assessment.resolved:
                cursor.execute("SELECT clock_timestamp() AS now")
                now = cursor.fetchone()["now"]
                measured = row["ts_verificado_ok"]
                if (not isinstance(measured, datetime) or measured.utcoffset() is None
                        or not row["ts_injecao"] <= measured <= now):
                    raise RoundError("success requires a valid measured recovery timestamp")
                if row["braco"] == "hitl":
                    cursor.execute("SELECT * FROM audit_log WHERE experiment_run_id = %s FOR UPDATE", (run_id,))
                    linked = cursor.fetchall()
                    if len(linked) != 1:
                        raise RoundError("HITL success requires exactly one linked incident")
                    incident = linked[0]
                    if (not target_matches(row["host_alvo"], incident)
                            or not timestamps_match(row, incident, now)
                            or incident["versao_kb"] != row["versao_kb"]
                            or incident["regra_disparada"] != EXPECTED_RULES[row["cenario"]]
                            or incident["decisao_humana"] is not True
                            or incident["ts_aprovacao"] is None
                            or not incident["ts_criacao"] <= incident["ts_aprovacao"] <= measured
                            or incident["status_execucao"] != "sucesso" or incident["exit_code"] != 0):
                        raise RoundError("HITL incident does not support a successful human assessment")
            cursor.execute(
                "UPDATE experiment_run SET passos_manuais = %s, comandos_usados = %s, "
                "resolvido = %s, observacoes = %s WHERE id = %s",
                (assessment.manual_steps, assessment.commands, assessment.resolved, assessment.observations, run_id),
            )


def discard_round(connection, run_id: int, reason: str) -> None:
    require_text(reason, "discard reason")
    require_idle(connection)
    with connection.transaction():
        with connection.cursor() as cursor:
            row = locked_round(cursor, run_id)
            if row["descartada"]:
                if row["motivo_descarte"] == reason:
                    return
                raise RoundError("an existing discard reason cannot be replaced")
            cursor.execute("UPDATE experiment_run SET descartada = TRUE, motivo_descarte = %s WHERE id = %s",
                           (reason, run_id))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    link = sub.add_parser("link", help="link explicit incident and Zabbix event IDs")
    link.add_argument("--run-id", type=int, required=True)
    link.add_argument("--incident-id", type=int, required=True)
    link.add_argument("--event-id", required=True)
    assess = sub.add_parser("assess", help="record human assessment without changing timestamps")
    assess.add_argument("--run-id", type=int, required=True)
    assess.add_argument("--record-file", type=Path, required=True)
    discard = sub.add_parser("discard", help="retain evidence and add a discard reason")
    discard.add_argument("--run-id", type=int, required=True)
    discard.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        assessment = None
        if args.action == "assess":
            record_file = args.record_file if args.record_file.is_absolute() else ROOT / args.record_file
            record = json.loads(record_file.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or set(record) != set(MANUAL_FIELDS):
                raise ValueError("assessment file must contain exactly the four manual fields")
            assessment = Assessment(record["passos_manuais"], record["comandos_usados"],
                                    record["resolvido"], record["observacoes"])
            assessment.validate()
        with conectar() as connection:
            if args.action == "link":
                match = link_incident(connection, args.run_id, args.incident_id, args.event_id)
                print(json.dumps({"run_id": args.run_id, "incident_id": args.incident_id,
                                  "expected_rule": match}))
            elif args.action == "assess":
                assess_round(connection, args.run_id, assessment)
            else:
                discard_round(connection, args.run_id, args.reason)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, (RoundError, ValueError)) else type(exc).__name__
        print(f"Operation aborted: {detail}.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
