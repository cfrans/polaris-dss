# R003 laboratory controller

Prepared and tested offline on 2026-10-06. PostgreSQL locks, actual SSH, sudo/systemd and the
integrated two-arm experiment have **not been validated**. Shell tests use fake systemctl/id
commands in a temporary directory. No real service or research data was used in those tests.

## Preconditions and credentials

Use a disposable target with the intended nginx service. The controller changes only that service;
it does not validate unrelated services, disk/CPU scenarios, NTP or Zabbix alert rearming.
Before a rehearsal, confirm the frozen code/image, KB, time synchronization, prior alert closure,
round order and absence of unrelated faults. Wait at least five minutes between rounds as required
by the protocol. Operator actions start only after the actual monitoring alert.

The existing `TARGET_SSH_HOST`, `TARGET_SSH_USER`, `TARGET_SSH_KEY_PATH` and database configuration
are used for independent read-only verification. Supply a **separate administrative SSH username
and private key** for injection and post-round reset; the service username and key path are refused.
This checks configured identities/paths, not whether copied files contain the same key. The
administrator must establish distinct credentials and permissions before the laboratory rehearsal.
Non-root administrative users need noninteractive sudo for the fixed timeout/bash command; root
runs it directly. Unknown or changed SSH host keys are rejected by the existing transport.

No credential, sudo permission or host-key trust is installed by this controller. Administrative
key files must be readable in the execution environment and kept outside Git. If running in a
container, arrange their availability separately. The administrative identity is for laboratory
instrumentation; the HITL remedy continues through the existing persisted approval workflow.

## Run either arm

Use the project's Python environment. From the repository root, substitute actual metadata:

```bash
python -m experiment.scenarios.service_controller run --arm <baseline_or_hitl> --repetition <n> --operator <operator_label> --system-version <frozen_release_label> --timeout <observation_seconds> --admin-user <administrative_user> --admin-key-file <private_key_path>
```

The target is always `TARGET_SSH_HOST`; the scenario is always `service_down` / nginx. A source
checkout captures Git HEAD and refuses tracked changes. The operator must also check untracked
source/configuration and confirm the running API image matches that revision. KB version is read
from the configured local knowledge base; the release label is provided explicitly, not inferred.
The observer uses the same target and verifier in both arms.

Docker images exclude Git metadata. In that environment also supply `--commit-sha <full_build_sha>`
from the verified image build, not an arbitrary newer host checkout. Git is not needed in the image.
In a source checkout a supplied SHA must match HEAD. The controller cannot independently establish
image provenance or the correspondence between the local KB and a separate running API.

Sequence:

1. Acquire the PostgreSQL advisory lock for the configured target. Another controller for that
   target string is refused; aliases must not be used to run concurrent sessions on one physical host.
2. Refuse prior unassessed R003 rounds and pending/executing R003 incidents for that target.
   Confirm healthy nginx through the independent verifier and the administrative script's check.
3. Wait 60 seconds, then repeat those checks. An unhealthy environment is refused, not repaired.
4. Persist and commit the round and `t0` using the existing registration helper.
5. Start the independent observer on its own PostgreSQL connection, wait until it claims the row,
   then send the fixed `inject` script through administrative SSH stdin. The script checks that
   nginx is active, stops it and verifies inactive state. It accepts no service names or shell commands.
6. Print the JSON `injected` event with the round ID. In another terminal/browser the operator
   performs the normal baseline runbook or HITL decision. The controller does not approve or recover.
7. Wait for an observed failure followed by three healthy checks; print `recovery_measured` with
   the database timestamp of the first successful sample. Stop the observer and release locks.

`t0` precedes observer arming and dispatch; it includes that instrumentation/SSH delay, not the
exact physical stop instant. Observe this overhead in rehearsal, use the same procedure in both
arms and record its limitation. The observation deadline starts when the observer is armed and
is distinct from the rule's execution timeout. If failure is missed, no `t5` is invented.

Failed injection or observer startup discards the row through the registration helper and reports
its ID. A later observation/transport timeout leaves the injected round unassessed: the operator
must classify a valid failed attempt or discard invalid measurement with a reason. Cancellation
requests observer shutdown; a shutdown failure is reported with the round ID. No automatic reset
occurs after success, error or cancellation. Check database evidence if output or connectivity fails.

## Link, assess and preserve evidence

Use [round management](../rounds.md) with the IDs returned by the controller. For HITL, link the
explicit incident/event before assessment. A pending recommendation must be approved or rejected
through the normal UI. Record actual actions, commands and correctness; recovery measurement does
not populate `resolvido`. Valid failures remain in the accuracy denominator. If a false negative
has no incident, assess it as a failed attempt rather than discarding it solely for that reason.
Save the per-round database backup before resetting and review collateral effects before success.

## Explicit post-round reset

After human assessment or discard, invoke:

```bash
python -m experiment.scenarios.service_controller reset --run-id <round_id> --admin-user <administrative_user> --admin-key-file <private_key_path>
```

The round must match R003 and the configured target. Reset is refused for an unassessed valid row,
another unassessed R003 round on that target or a linked pending/executing incident. It sends only
`systemctl start nginx` and checks health using both the script and independent verifier. It changes
no database timestamps, assessments, links or decisions. It does not restart a running service,
reconfigure nginx or repair other faults. Wait for the monitoring problem to close before the next
round. If the initial target is unhealthy before any round exists, restore it manually and diagnose
the cause; that is outside this post-round reset command.

Commands return zero on measured recovery/confirmed reset and two on errors. A successful recovery
exit is a measurement result; the human assessment determines protocol accuracy. Credentials and
remote stderr are not printed. Use discarded rehearsal rounds to validate this complete workflow
before collecting official data.
