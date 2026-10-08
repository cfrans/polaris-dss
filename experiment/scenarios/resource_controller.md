# CPU and disk laboratory controllers

Prepared on 2026-10-06. Persistence, locks and API accuracy were tested in disposable PostgreSQL
16.15. Shell actions were tested with fake Linux utilities and temporary files. **Actual target
SSH/sudo, systemd, CPU utilization and disk allocation have not been validated.** No research
results were collected. These are operator-invoked instruments for a disposable laboratory target.

## Shared workflow

Use the same database, target and separate administrative SSH identity described in the
[R003 controller](service_controller.md). The Polaris identity sends read-only verifiers without
sudo. No keys, privileges, mounts, packages or approval records are installed by these commands.
Freeze the source/image SHA, KB and randomized order, synchronize clocks, close prior alerts and
check collateral effects before rehearsal. The controller checks the selected resource only;
it does not replace the full environment checklist. Use one canonical target string.

The controllers share the same target lock with R003. They refuse any unassessed, non-discarded
round or pending/executing R001/R002/R003 incident on that configured target. They check health,
wait 60 seconds, repeat checks, commit `t0`, arm the observer on a separate connection, and then
inject. The operator conducts baseline or persisted HITL approval in another terminal/browser.
Failures preserve/discard evidence using the same rules as R003. No recovery happens automatically.

From the repository root, substitute real values:

```bash
python -m experiment.scenarios.resource_controller <disk_full_or_cpu_high> run --arm <baseline_or_hitl> --repetition <n> --operator <operator_label> --system-version <frozen_release_label> --timeout <observation_seconds> --admin-user <administrative_user> --admin-key-file <private_key_path>
```

Images without Git metadata require `--commit-sha <full_build_sha>`. Confirm that the running API
uses the same source/KB; a supplied build SHA does not independently prove image provenance.
`t0` includes observer arming and SSH dispatch overhead, before the physical fault. Disk injection
also validates its gzip before allocation; measure this overhead in rehearsal in both arms.
Observation starts before injection and can expire without ever seeing a fault. Never invent `t5`.

The JSON `injected` event supplies the round ID. Link the explicit incident/event for HITL and
[assess or discard the round](../rounds.md) after measurement. Human correctness includes diagnosis,
rule timeout and collateral effects. Save database evidence before resetting. Close **all**
pending/executing incidents on the target before reset, including unlinked baseline recommendations.

```bash
python -m experiment.scenarios.resource_controller <disk_full_or_cpu_high> reset --run-id <round_id> --admin-user <administrative_user> --admin-key-file <private_key_path>
```

Reset requires a matching assessed/discarded round and no other open round/incident. It changes
only the instrument's target state and verifies health, preserving timestamps, assessment and audit.
Wait for Zabbix alert closure and the protocol's minimum five-minute spacing before the next round.
An unhealthy initial environment without a registered round requires explicit administrative review.

## R002: one available CPU and one owned workload

The script refuses injection unless `nproc` reports **one available CPU**, `/usr/bin/stress-ng`
exists, no `stress`, `stress-ng` or `stress-ng-cpu` process is present, and the fixed experiment unit
is absent. Confirm the target's CPU allocation/cpuset and the tool version during rehearsal.
The current remediation terminates one candidate process; the instrument creates one CPU worker
rather than assuming that killing one of several workers restores whole-host health.

Injection creates `polaris-experiment-cpu.service` with a fixed description, `Type=exec`,
`Restart=no`, `KillMode=control-group` and `--collect`, running `stress-ng --cpu 1 --cpu-load 100`.
A 3600-second runtime/stress-ng limit prevents indefinitely abandoned load. The CLI limits
observation to at most 1800 seconds, so safety expiry cannot close a still-active measurement.
Natural exit or safety expiry is not a successful human remediation; inspect unit logs and discard
an invalid rehearsal. The script confirms active state; the observer must independently see high
CPU. Unit-name collisions with a different description are refused. Reset stops only the owned
unit, rather than running a process-name-wide kill. A collected, already absent unit is acceptable.

The observer sends `verify_cpu.sh`, validates its percentage and exit status, and requires CPU
below 70% for a **30-second sequence of healthy samples**, followed by three qualifying checks.
Any unhealthy sample restarts that window. `t5` is the database time of the first qualifying sample
at/after the 30-second window, confirmed by the next two. An observed unhealthy sample is mandatory.
Samples remain sequential; `top` and SSH can make intervals longer than one second. The sampled
window does not prove continuous CPU behavior between probes. Use identical criteria in both arms.

## R001: isolated 2 GB filesystem and tracked disposable data

Only `/mnt/polaris_test` is supported. The script requires an actual mountpoint on a different
filesystem device from `/`, a reported size between 1.9 and 2.2 billion bytes, and no unrelated
entries. Empty `lost+found` is accepted; recovered files inside it are refused. The script does
not create/format/mount a volume and never accepts `/var/log` or a user-supplied path.

Before each round, explicitly prepare the gzip fixture while the filesystem is empty:

```bash
python -m experiment.scenarios.resource_controller disk_full prepare --admin-user <administrative_user> --admin-key-file <private_key_path>
```

This creates `polaris_r001_lab.log.gz` from 400 MiB of random input, verifies gzip integrity,
sets its age to eight days and records a root-owned 0600 `.polaris-r001.state` manifest. Preparation
is outside the measured round; it must finish within the transport's 180-second deadline. The
round's own 60-second settling period follows preparation. A partial preparation remains visible
for administrative review; it does not create a retrospective round. If preparation failed before
any round exists, the administrator may explicitly send the fixed disk script with `reset` after
checking that no round/controller is active. Do not remove an untracked fixture blindly.

The manifest pins the mount device and archive/filler inodes. Existing fixture files without the
manifest, replacements, symlinks and files with multiple hard links are refused. Preparation does
not overwrite existing entries. The prepared gzip must be roughly 400 MiB, older than seven days,
and the filesystem below 35% usage before injection.

After `t0` is committed, injection creates tracked `enchimento.bin` using `fallocate`, targeting
96% based on GNU df's used/available denominator (reserved root blocks excluded). Final usage must
be between 96% and 98%. The intended remedy removes the disposable gzip, creating enough space
for the verifier's **strictly below 85%** criterion. The existing cleanup script also invokes global
logrotate when present; collateral review outside the test mount remains necessary. No remedy is
invoked by the controller. The observer requires an observed unhealthy sample and then three
consecutive healthy responses; `t5` records the first confirmed healthy sample.

Reset removes only the manifest-identified archive, filler and manifest, and requires usage below
35%. A removed archive is normal after approved cleanup; a replacement inode is refused. These
checks protect the instrument's own calls, not arbitrary concurrent root commands or mount changes.
Preserve test-volume identity throughout each round and forbid concurrent administrative changes.

## Rehearsal requirements

Use discarded rounds in both arms. Validate mount/device checks, GNU utility versions/behavior,
CPU count, systemd privileges, no automatic workload restart, transport cancellation/timeout,
actual failure observation, t0-to-fault delay, CPU sampled 30-second window, post-remedy disk headroom,
and safe reset after a valid failure. The global reset checklist and aggregate MTTR/manual-step
analysis are separate requirements; these per-scenario commands do not complete the experiment.


Before a controller invocation, use the [global environment checklist](reset_environment.md) to
inspect all scenarios, not only the injected one. After assessment/discard, its explicit reset
command restores the round's scenario and verifies the other scenarios without repairing them.
The remaining NTP, monitoring rearming, five-minute interval and collateral checks are manual.
