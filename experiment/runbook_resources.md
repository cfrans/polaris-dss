# R001/R002 manual baseline

Prepared on 2026-10-06; the real two-arm laboratory rehearsal remains unvalidated. Follow the
shared alert-driven start, actual-action counting and evidence rules in
[the R003 baseline runbook](runbook_baseline.md). Use the same independent resource observer in
both arms, via [the resource controller](scenarios/resource_controller.md). Injection/reset are
instrumentation; do not include them as operator remediation steps or run reset before assessment.

## R001: disk pressure

1. Wait for the real Zabbix alert, open its details and identify the host and mount.
2. Establish the administrative SSH session. Run `df -h /mnt/polaris_test` and inspect usage.
3. Inspect the compressed files and timestamps on the isolated volume; confirm the scenario's
   disposable gzip and absence of needed data. Record every inspection command.
4. Apply the same frozen `src/scripts/disk_cleanup.sh` used by HITL, explicitly as the administrator,
   with only `/mnt/polaris_test`. Since scripts are central, do not assume a copy exists on the target.
   From the source checkout, one way to send the frozen bytes manually is:

   ```bash
   ssh -i <administrative_key> <administrative_user>@<target> 'sudo -n /usr/bin/timeout -k 5s 60s /usr/bin/bash -s -- /mnt/polaris_test' < src/scripts/disk_cleanup.sh
   ```

   Use the account's established authorization and host-key trust. A root account omits `sudo -n`.
   Do not install credentials or loosen sudo during the round. Record the command and additional SSH
   session according to the step definition, including retries. This is an explicit manual action,
   separate from the Polaris remediation executor and from experimental reset.
5. Run `df -h /mnt/polaris_test` for operator confirmation. The observer defines `t5`.
6. Inspect collateral effects, including the existing script's global logrotate invocation, and
   classify correctness using the protocol before entering the human assessment.

## R002: CPU pressure

1. Wait for the real Zabbix alert, open its details and identify the host.
2. Establish the administrative SSH session. Run `top -bn2 -d 1 -o %CPU` and inspect the second
   sample; the first reflects a longer history.
3. Inspect the leading PID using `ps -p <pid> -o pid,comm,args -ww` and, when needed,
   `systemctl status polaris-experiment-cpu.service --no-pager`. Confirm that the candidate belongs
   to the experiment and matches the approved process allowlist. Record those commands.
4. Run `sudo kill -TERM <confirmed_pid>` for that candidate only. Inspect whether it exited. If
   TERM is ineffective after the same ten-second wait as the frozen remedy, send
   `sudo kill -KILL <confirmed_pid>` and record that additional action. Do not substitute a broad
   `pkill` or instrument reset as the baseline remedy.
5. Inspect CPU again for operator confirmation. The independent observer requires the same
   sampled thirty-second recovery window and confirmation in both arms.
6. Confirm correct candidate, rule timeout and absence of collateral effects before assessment.

For HITL, read the recommendation and approve through the normal UI only after the actual alert.
Count actual operator actions rather than substituting a fixed expected count. A measured healthy
resource alone does not establish a correct diagnosis. Assess valid failure as false; discard only
invalid measurements with a reason. Preserve database backup, screen recording and literal commands
before an explicit post-round reset, and allow the monitoring alert to close before repeating.


Use the [global environment checklist](scenarios/reset_environment.md) before the next round and
after the explicit post-round reset. Preserve the raw evidence before cleanup; a successful health
check does not replace human correctness assessment. [Report analysis](analysis/report.md) exports
MTTR, recorded manual steps and human-assessed accuracy without editing primary data.
