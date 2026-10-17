# Read-only diagnostics and specific action plans

For R001/R002/R003, ingestion first commits the incident and its receipt timestamp. A separate
fixed collector then inspects the configured target over SSH. The event IP must match that
target; event data never selects another host. While collection is running, approval and display
timestamp registration are unavailable. Diagnostic time remains inside end-to-end recovery time.

The collector has an eight-second remote deadline. Disk inspection samples at most 256 directory
entries on `/mnt/polaris_test` and checks open descriptors. CPU inspection compares `/proc` CPU
ticks over one second for at most 512 processes. Nginx inspection reads its service state, up to
40 recent journal messages and the last 16 KiB of its fixed error log. Only recognized error
phrases and their source are exported, not complete log lines or credentials. These are clues,
not verified root causes. Missing evidence does not enable a generic destructive fallback.

## Choosing and approving an action

The incident shows ordered applicable options and their concrete target. Select an option,
review its metadata and reversibility, then approve. Low confidence or destructive actions require
an additional confirmation. Use **Atualizar diagnóstico** if the five-minute snapshot expired.

- Disk: individual compression of a closed `.log` when temporary space is sufficient, or removal
  of a root-owned regular `.log.gz` retained for at least seven days. Group/world-writable files,
  multiple hard links, symlinks, open files, path traversal and other volumes are refused.
  Displayed age does not establish that a log is operationally disposable; the operator reviews
  that choice. There is no global log rotation or recursive deletion.
- Nginx: start or restart when the observed inactive/failed state permits it. Known configuration,
  permission or port errors require investigation instead of blindly retrying a restart.
- CPU: terminate only the identified allowed process while its sampled usage meets the threshold.
  A pidfd binds signals to that process; another process never replaces it after approval.

The browser submits only an option ID, plan hash and reviewed script-catalog hash. The server
validates these against the stored snapshot, current rule and preferences. It commits the selected
operation together with human approval before reaching the executor. The executor rechecks the
snapshot and target identity. A changed file, process or service state refuses the action.
Evidence refresh keeps previous snapshots and cannot overwrite a newer concurrent refresh.

## Preferences

Open **Ferramentas → Preferências**. Settings are shared by operators on that server and stored
in the singleton `preferencias_operacionais` table (migration 009). The application retains its
existing trusted-network deployment boundary; these controls do not introduce operator authentication.

The default uses frequent choices only to break equal technical confidence. Another mode applies
an explicitly displayed preference discount, never a confidence bonus. A third ignores preference.
Defaults are five previous choices and a maximum 10% discount, configurable up to 25%.

Technical success/failure uses the existing F3 thresholds for each operation, avoiding applying
one candidate's history to all others. Preference mode uses
`C_display = C_technical * (1 - max_discount * (1 - choices / most_chosen_count))`
after the configured minimum. Counts cover approved choices for the same host and rule over
90 days; preference is not evidence of success or probability. All inputs and factors are stored
with the plan. Saving preferences increments their version and invalidates pending snapshots.

When `POLARIS_CONFIDENCE_HISTORY=false`, operation history and preference effects are disabled;
saved settings remain available but do not change recommendations. Keep that setting during
controlled measurements and rehearse the updated workflow before collecting official data.

## HTTP additions

`GET/PUT /api/v1/preferencias` reads/saves the validated settings. Incident detail includes
`plano` and `acao_escolhida`. Decision additionally requires `opcao_id` and `versao_plano` for
planned actions. `POST /api/v1/incidentes/{id}/diagnostico` refreshes a still-pending incident;
it performs inspection only and never executes remediation.

No action is automatically approved. The standalone scripts also support explicit administrative
manual operation; invoking them outside the application does not impose an audit approval guard.
