# Global experiment checks and explicit reset

This command inspects all three experiment scenarios together. It has a read-only check mode and
an explicit post-round reset mode. Automatic checks were tested locally with fake transports,
temporary shell fixtures and disposable PostgreSQL; physical SSH/systemd, real pressure and Zabbix
rearming require laboratory rehearsal. No automatic result certifies readiness for collection.

Use the existing database/target configuration and a separate administrative SSH username/key,
as in the [service controller](service_controller.md). Host-key verification remains required.
The command installs no credential, sudo permission or host-key trust. Configured service identity
and key path cannot be reused for administrative instrumentation.

## Read-only checks

From the repository root:

```bash
python -m experiment.scenarios.reset_environment --check --admin-user <administrative_user> --admin-key-file <private_key_path>
```

This requires a clean test filesystem without a prepared disk fixture. To check immediately before
a round, also pass `--scenario service_down`, `--scenario cpu_high` or `--scenario disk_full`.
For disk, first prepare the fixture explicitly using the existing resource controller; the disk
preflight requires that prepared fixture. For service/CPU, leftover disk fixtures are refused.

Under the shared target lock, the command:

1. Refuses earlier unassessed, non-discarded rounds and pending/executing R001/R002/R003 incidents.
2. Checks nginx is active, CPU instrumentation has no existing unit/stress process and the disk
   mount is isolated, about 2 GB and free of unrelated data. CPU instrumentation requires one
   available CPU. The disk check preserves every file; an empty-fixture check never resets it.
3. Runs the independent nginx/CPU/disk health probes without sudo.
4. Waits 60 seconds and repeats all checks. These two samples do not prove continuous health.

Inspection uses administrative privileges only for the fixed instrumentation check scripts.
No check creates a fixture, injects a fault, stops/starts a service or removes a file. Failure
aborts and releases the lock; it does not automatically repair the condition.

## Explicit post-round reset

Assess or discard the round, close linked/target pending incidents and preserve its evidence first:

```bash
python -m experiment.scenarios.reset_environment --reset-run-id <round_id> --admin-user <administrative_user> --admin-key-file <private_key_path>
```

The scenario is read from that round, and its target must match the configured target. Do not pass
`--scenario` during reset. The existing controller guards refuse an unassessed valid round, another
unassessed round or a linked/target pending/executing incident before any reset action.

Only that round's scenario is restored: start nginx for R003, stop only the owned CPU unit for
R002, or remove only manifest-tracked disk artifacts for R001. No other scenario receives reset.
The shared target lock remains held through reset and both global inspection passes. Assessment,
timestamps, approvals and operational audit records are unchanged. If another scenario is dirty
following reset, the command reports failure rather than cleaning it. A failure after reset may
mean its action already occurred; inspect the target and existing evidence before retrying.

Exit 0 emits JSON with `automatic_checks_passed`, target, optional `reset_run_id` and an explicit
`manual_checks_required` list. Exit 2 means inspection/reset was not fully confirmed. Unknown or
changed host keys and unexpected script output are refused; credentials and remote stderr are not
printed. Check evidence after interruption or transport error; no automatic reset follows errors.

## Mandatory manual checklist

- Confirm NTP/skew on the controller, Zabbix and target.
- Confirm old monitoring problems closed and triggers rearmed, without duplicates.
- Wait at least five minutes between rounds; the 60-second check is not that interval.
- Confirm frozen SHA/image/KB, scenario/arm order and identical monitoring intervals.
- Save raw round/audit evidence before reset and inspect unrelated services/files for collateral effects.

Use this checklist before each controller invocation. The existing controllers retain their own
scenario checks; invoking one alone does not invoke this global checklist. No shell script performs
a bulk reset of unrelated workloads. The HITL executor still requires persisted human approval;
administrative laboratory reset is a separate, explicit operation.
