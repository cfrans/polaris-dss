# Round registration, incident linking and human assessment

Status: tested with simulated database responses on 2026-10-06. Actual PostgreSQL
transactions, locks and integration with the laboratory have **not been validated**.
These tools do not approve incidents or execute recovery commands. No results have been collected.

## Registration contract for an injection controller

`experiment.rounds.register_injection(connection, metadata, inject)` uses the existing
`experiment_run` schema. Supply a dedicated idle connection opened with `conectar()` without
autocommit, a `RoundMetadata` record and a trusted injection callback. The metadata contains:

- `scenario`: `service_down`, `disk_full` or `cpu_high`;
- `arm`: `baseline` or `hitl`, and `repetition`: the positive repetition number;
- actual `system_version`, full 40-character lowercase `commit_sha` and `kb_version`;
- `target`: target IP or hostname, and `operator`: the actual operator label.

The function inserts `ts_injecao` using the PostgreSQL clock and commits **before** calling
`inject(run_id)`. An insert or commit failure cannot reach injection. The callback must check the
injection outcome, raise on failure and return `None` on success; returned status codes are refused.
On failure or interruption the round is discarded with the exception type, retaining its ID and
original timestamp. The exception message is not stored because it might contain credentials.
`InjectionFailed.run_id` identifies the affected row. If persisting the discard also fails, the
exception reports that fact; inspect the row and target before retrying. There is no automatic reset. Keep callback setup outside the measured interval; the committed ID
allows the controller to coordinate the observer and the declared injection.

The actual scenario controller, environment checks and injection transport are still absent.
There is deliberately no retrospective CLI registration: never invent `t0` after a manual fault.
The helper cannot verify the callback's scope, software metadata or clean environment; its caller
must establish those conditions. For the R003 observer, `target` must equal `TARGET_SSH_HOST`.

## Link the explicit HITL incident

Use the existing Python environment and database configuration. From the repository root:

```bash
python -m experiment.rounds link --run-id <round_id> --incident-id <incident_id> --event-id <zabbix_event_id>
```

The row must belong to the HITL arm and remain unassessed and undiscarded. Linking checks the
explicit incident/event IDs, target, knowledge-base version and timestamps:
`ts_injecao <= ts_deteccao <= ts_criacao <= ts_verificado_ok` when recovery is measured;
otherwise the database's current time bounds the incident. Future times and missing detection
times are refused. Target IPs are compared as addresses; a hostname is matched literally.
Clock skew and timestamp precision problems must be investigated, not bypassed by altering evidence.

Only `audit_log.experiment_run_id` is updated. Another incident cannot replace the round's link,
and an incident cannot be reassigned to another round. Repeating the same link is idempotent while
the round remains open. These rules use row locks and a conditional update within a transaction;
they do not prevent arbitrary direct SQL outside this tool.

The JSON output includes `expected_rule`. A wrong rule is still linked with `expected_rule=false`
to preserve evidence of failure. Exit code zero means linking completed, **not** correct resolution.
A false negative can be assessed without an incident. Baseline rounds cannot link Polaris incidents.

## Record the human assessment

After the observer and operator review, create a UTF-8 JSON file with **exactly** these fields:

| Field | Required value |
|:---|:---|
| `passos_manuais` | Actual nonnegative integer count; not a preset count for either arm |
| `comandos_usados` | Literal commands as a JSON string; use `\n` between commands, or `""` if none |
| `resolvido` | Explicit JSON boolean `true` or `false` |
| `observacoes` | Nonblank operator observations, including deviations and review of resolution |

Use measured values and observed outcomes, not example data. Do not include credentials. Relative
file paths are resolved from the repository root, including when invoked from another directory.

```bash
python -m experiment.rounds assess --run-id <round_id> --record-file <assessment_json_path>
```

The command only fills the four manual fields; it preserves `t0`, `t5`, links and approvals.
It refuses to replace any existing assessment field. `resolvido=true` requires a measured recovery
between injection and current database time. HITL additionally requires exactly one linked incident
for the expected rule, target, KB and time window, with persisted human approval before recovery,
execution status `sucesso` and exit code zero. These are minimum data checks: the operator must
also confirm correct diagnosis, recovery within the rule's timeout and absence of collateral effects.
The observation timeout is not the rule's remediation timeout.

`resolvido=false` does not require an incident or `t5`. Valid failed attempts remain undiscarded
and must be included in the accuracy denominator. Once assessed, the observer cannot write a later
recovery timestamp into that row. A measurement error is different from a failed remediation.

## Discard invalid measurement without deleting evidence

```bash
python -m experiment.rounds discard --run-id <round_id> --reason '<actual measurement error>'
```

This changes only `descartada` and `motivo_descarte`, retaining times, human assessment and audit
links. Repeating the same reason is idempotent; replacing an existing reason is refused. Discard
an invalid measurement or rehearsal, not an undesired but valid failed outcome. Preserve backups.

Commands return zero on completion and two on operational or validation errors. A database error
prints its type rather than connection details. These writes commit their own transactions.
The CSV exporter preserves incomplete, failed and discarded rows. Human-assessed accuracy is
prepared in [analysis/accuracy.md](analysis/accuracy.md), including failed rounds without incidents.
The database view requires migration 007; an unmigrated view still uses approved execution outcomes.
Real PostgreSQL validation remains required before official collection.
