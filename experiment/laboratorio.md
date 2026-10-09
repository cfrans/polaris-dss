# Laboratory rehearsal workspace

Use **Laboratório** in the Polaris header, or open `/laboratorio.html`. This page prepares
commands, shows the existing diagnostic on request, provides the manual/HITL procedure and
downloads an assessment draft. It does not inject, approve, assess or reset over HTTP.
Configuration and checkboxes stay in page memory only. Reloading clears the draft.

The helper `lab.py` runs on the **Linux collection host**, from the repository checkout, with
Python 3 and the existing Docker Compose plugin. It uses Python's standard library; no virtual
environment or new package is needed. Docker must be running. It never installs software,
keys, sudo permissions or host-key trust. The temporary controller uses the immutable image ID
of the running API, not a mutable tag. Only administrative operations mount the administrator's
private key, read-only, in a temporary container running as root. The permanent API keeps its
service identity and mounts. A separate administrative key/user and private file permissions
are required; identical private key files are rejected even if copied under a different path.
This is root laboratory access, not a command-restricted credential.

These launchers have been prepared for offline verification. **Not validated in the laboratory:**
temporary Compose mounts, integrated controllers, real timings, pressure and the two-arm workflow.
Rehearsal must precede official collection. An SSH `id -un` success is not controller validation.

## 1. Prepare the workspace once

Use a clean checkout of the revision being tested. Build/deploy API and reconciler from the same
revision, apply migrations and keep the image/SHA/KB evidence. The API version string alone does
not identify an image. Do not change code or configuration halfway through a comparison.

In the server checkout:

```bash
python3 experiment/lab.py --help
python3 experiment/lab.py inspect
```

Inspect prints checkout SHA, immutable API image ID, tracked-change state, services, migrations
and the masked diagnostic. It neither injects nor repairs. Keep those outputs as setup evidence.
Also review untracked files and the actual build history; pinning an image does not prove its SHA.
Before controlled conditions, set `POLARIS_DEBUG=false` and `POLARIS_CONFIDENCE_HISTORY=false`
in the existing `.env` and recreate **both** API and reconciler after saving. Do not print `.env`
or copy credentials into evidence. Confirm the effective values through the diagnostic.
The launcher refuses `run` when live API/reconciler settings diverge from Compose or when history
or debug remain enabled. It reads only selected non-secret fields for that comparison.

Create a Proxmox snapshot appropriate to the disposable target and preserve an initial database
backup. Confirm one CPU (`nproc`), nginx, the isolated approximately 2 GB mount at
`/mnt/polaris_test`, supported utilities, synchronized clocks, closed previous alerts and absence
of duplicate triggers. Do not format, mount or delete data just to make a check pass.
Freeze scenario/arm order, monitoring intervals and observation limits. Allow at least five minutes
between rounds. Record exact tool versions and any protocol deviation.

Open three separate working areas:

1. Instrumentation: server terminal for the controller and this preparation page.
2. Operator: Zabbix plus an administrative terminal for baseline; Zabbix plus Polaris for HITL.
   Baseline operator starts on the actual Zabbix alert, without using the Polaris recommendation.
3. Evidence: screen recording/prints, literal actions and output location on the collection host.

The page defaults to R003 and baseline; enter the actual operator, frozen version label and full
40-character build SHA. Repetitions are not randomized automatically. Use the same scenario,
observer and initial conditions for both arms. Rehearsal rows must be discarded with a reason
before any official report is interpreted. Do not reuse a discarded round as an official result.

## 2. Check, inject and observe

The examples below use the laboratory's separate root key. Substitute the confirmed account/key
if different. Relative paths resolve from the repository, even when launched elsewhere; `~` in
the key argument is expanded by the helper.

```bash
python3 experiment/lab.py check --scenario service_down --admin-user root --admin-key-file '~/.ssh/id_ed25519'
```

The global check inspects all three scenarios twice, separated by 60 seconds. It refuses old
unassessed rounds, pending/executing incidents and unrelated fixture data. It does not replace
clock/alert/image/order/interval checks and does not certify readiness for collection.

For R001 only, prepare the tracked disposable gzip **before** the disk-specific global check:

```bash
python3 experiment/lab.py prepare --scenario disk_full --admin-user root --admin-key-file '~/.ssh/id_ed25519'
python3 experiment/lab.py check --scenario disk_full --admin-user root --admin-key-file '~/.ssh/id_ed25519'
```

`prepare` creates files on the already isolated volume. If preparation fails before a round exists,
inspect and document the state; there is no automatic cleanup or invented round ID.

Fill the page metadata and copy its generated **run** command. Equivalently, replace every
placeholder below before running (the angle brackets are not executable arguments):

```text
python3 experiment/lab.py run --scenario <service_down|cpu_high|disk_full> --arm <baseline|hitl> --repetition <number> --operator '<actual operator>' --system-version '<frozen label>' --commit-sha <full SHA> --timeout <seconds> --admin-user root --admin-key-file '~/.ssh/id_ed25519'
```

This command changes the selected target scenario. It commits t0 before arming observation and
injection. Keep the terminal open, save the printed `run_id`, then let the operator perform the
selected arm only after the real alert. A successful health observation records t5, not correctness.
CPU observation must be at most 1800 seconds, below the safety expiry. Errors/interruption do not
reset automatically; inspect the reported row and target rather than blindly rerunning.

Follow [nginx baseline](runbook_baseline.md) or [CPU/disk baseline](runbook_resources.md) for actual
manual actions. For disk, send the frozen central script's bytes as described in that runbook;
the helper does not provide a second remediation executor. For HITL, approval/rejection remains
in the usual Polaris incident card with persisted approval before privileged execution.

## 3. Link and assess

Enter the controller's exact run ID in **Registrar**. In HITL also enter the exact Polaris
incident and Zabbix event IDs; copy the link command before assessment. A valid failed attempt
without a recommendation can be assessed negatively without inventing a link.

Enter actual steps, literal commands, explicit correctness and observations/collateral review.
Click **Baixar avaliação JSON**, then transfer the file to the **server path shown by the page**.
A browser download to the workstation is not yet a file on the collection server. The directory
can be created manually with `mkdir -p experiment/evidence/<session>`; replace the session name.
The assessment command mounts just that JSON read-only and invokes the existing transactional CLI.
Downloading a JSON does not write the database. Success requires independent measured recovery and,
for HITL, the required linked/approved/successful incident; those guards are unchanged.

Valid failed remediation is `resolvido=false`. Invalid measurement or rehearsal uses **discard**
with an actual reason. Descartes preserve timestamps/links/assessment, and existing human assessment
cannot be silently overwritten. Count retries and extra inspections; instrumentation is not an
operator action. Never copy passwords, tokens or private key contents into commands/observations.

## 4. Preserve, reset and repeat

The page generates commands with new per-session/per-round names:

```text
python3 experiment/lab.py backup --output experiment/evidence/<session>/rodada-<id>.dump
python3 experiment/lab.py report --output experiment/evidence/<session>/rodada-<id>-relatorio --kind collected
python3 experiment/lab.py reset --run-id <id> --admin-user root --admin-key-file '~/.ssh/id_ed25519'
```

Backup uses custom-format `pg_dump` on the database service. Existing output/partial files are
refused; a failed dump remains `.partial` and is not a complete backup. Report exports all rows,
CSV/Markdown/manifest without graphs to the **host**, using the checked-out `experiment/analysis`
mounted read-only only in that temporary process (analysis is excluded from the API image).
Use the frozen, verified analysis revision. Both outputs persist after removing the container.
Backup and report are separate snapshots; run them after recording/discarding and before reset,
when the round is stable. For synthetic fixtures use `--kind synthetic`, never relabel them collected.
Local evidence is excluded from Git and image builds. Raw publication remains a separate review.

Reset is explicit instrumentation, not baseline remediation. It accepts only the assessed/discarded
round, restores its scenario and then checks all scenarios. A dirty unrelated scenario can make
global confirmation fail after the selected reset; no further repairs are attempted. Confirm
collateral effects, alert closure/rearming and the five-minute interval before the next round.
Do not use a successful health check as a human correctness assessment.

For direct CLI contracts see [rounds](rounds.md), [R003](scenarios/service_controller.md),
[CPU/disk](scenarios/resource_controller.md), [global checks](scenarios/reset_environment.md)
and [reports](analysis/report.md).
