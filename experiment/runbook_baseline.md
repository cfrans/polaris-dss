# R003 manual baseline and recovery measurement

Status: prepared and tested offline on 2026-10-05. Shared persistence/locks were validated locally in disposable PostgreSQL on 2026-10-06.
Laboratory execution and SSH measurement have **not been validated**. No experimental results
have been collected by these tools. This procedure covers `service_down` only.

## Preconditions

- Use a disposable laboratory target and the same approved software revision in both arms.
- Restore nginx to active, clear the previous alert and close the previous round before starting.
- Open the Zabbix monitoring page before the round. The operator must wait for the actual alert;
  the observer does not notify the operator or diagnose the incident.
- Freeze the randomized round order before collection. These tools do not generate that order.
- A collection controller must create an `experiment_run` row and record `ts_injecao` using
  PostgreSQL time immediately before stopping nginx. The registration helper now enforces commit
  before a trusted injection callback. The R003 controller is prepared in
  [scenarios/service_controller.md](scenarios/service_controller.md); its real integration remains
  unvalidated. Explicit incident linking and human assessment are described in [rounds.md](rounds.md).
  Creating a row retrospectively is not an acceptable replacement for recording injection time.
- The row must identify `cenario=service_down`, the actual arm (`baseline` or `hitl`), the round,
  software revision, knowledge-base version, operator and target. `host_alvo` must equal
  `TARGET_SSH_HOST`. Use discarded rehearsal rounds before any official collection.

## Independent observer (both arms)

Use the project's existing Python environment and database/SSH configuration. Start from the
repository root in a separate terminal while nginx is down, before the operator can restore it:

```bash
python -m experiment.verify.service_watcher --run-id <round_id> --timeout <observation_seconds>
```

Choose and document the observation limit before the session; it is distinct from the remediation
timeout. The observer sends the current `verify_service.sh nginx` through SSH stdin with no sudo.
It never restarts nginx and never approves an incident. Unknown SSH host keys remain rejected.

Samples start one second apart when checks fit in that interval; slow checks are sequential and
reduce the sampling frequency. An initial healthy service cannot complete the measurement. After
an observed unhealthy state, three consecutive healthy samples confirm recovery. `ts_verificado_ok`
is the PostgreSQL timestamp taken immediately after the first sample of that successful sequence.
This is an observation time, with verification and network latency, rather than the exact instant
of recovery. A broken SSH connection or an unexpected verifier response aborts measurement.

The observer locks the round against another observer and conditionally writes only
`ts_verificado_ok`. A discarded, already measured or human-assessed row cannot be overwritten. It does not mark
`resolvido`, count operator actions or write approval records. If the observer misses the failure,
times out or loses connectivity, discard the rehearsal/collection round with a reason and repeat;
do not fabricate a recovery timestamp. Its timeout starts when observation starts, not at injection.

## Baseline operator procedure

After the Zabbix alert becomes visible:

1. Open the alert, identify the target and read the reported condition.
2. Establish the administrative SSH session normally used for manual recovery.
3. Run `systemctl status nginx --no-pager` and inspect the state. A nonzero exit while stopped
   is expected. If the diagnosis needs logs, run `journalctl -u nginx -n 30 --no-pager` and record
   that extra action.
4. Once the diagnosis is confirmed, run `sudo systemctl restart nginx` with the administrative
   account's normal authorization. Do not change the Polaris account or its sudo permissions.
5. Run `systemctl is-active nginx` for operator confirmation. The independent observer determines
   the experimental recovery timestamp in both arms.
6. Confirm correct diagnosis and absence of collateral effects before entering `resolvido=true`.
   Service health alone does not establish those conditions.

Record the actual count of monitoring navigation actions, SSH session openings, shell commands and
verification commands. Record commands literally, including unsuccessful commands and retries.
Keep the definition of a step identical between arms; do not substitute a fixed expected count.
The observer's probes and scenario injection are instrumentation and are not operator steps.
Record any deviation and decide whether the round must be discarded before analysis. Use the
assessment command in [rounds.md](rounds.md) after checking the measured recovery and the protocol's
correctness criteria. A valid failed outcome is recorded as `resolvido=false`, not discarded.

For HITL, the operator follows the same alert-driven start, reads the Polaris recommendation and
records each actual action, including approval. Normal persisted human approval remains mandatory
before the existing remediation executor can run. This runbook adds no alternative execution path.

## CSV export

From the repository root, with PostgreSQL reachable using the existing configuration:

```bash
python -m experiment.analysis.consolidar --output experiment/analysis/rounds.csv
```

The export is a raw snapshot of **all** `experiment_run` rows, including discarded and unfinished
rounds. It keeps metadata, literal commands, operator observations and UTC timestamps. A missing
recovery timestamp leaves `mttr_segundos` empty; it is never interpreted as zero or success.
Existing output files are refused: use a different filename for each snapshot. Timestamps are
validated before creating the file. No aggregate KPI tables, plots or audit timeline are produced.

Keep the CSV on the collection host and preserve the original database evidence. If running the
command inside a container, copy the output to the host before recreating the container; the image
filesystem is not durable evidence storage. Review exported observations/commands for credentials
and personal information before publishing raw data. Back up the database after each round.

The prepared CPU/disk manual procedures are in [runbook_resources.md](runbook_resources.md).
