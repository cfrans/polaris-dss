# Installation and operations

For a first installation, start with [the ordered installation guide](installation.md).
The in-app assistant at `/configuracao.html` tests and saves encrypted connections. It does not
provision external services. This reference covers ongoing operation and troubleshooting.

The supported controlled target is Ubuntu 24.04 LTS with systemd and nginx. Polaris runs through
Docker Compose; an existing Zabbix 7.0 LTS instance can be reused. The optional `zabbix` profile
is for an isolated installation, not a second production monitor. CPU/disk instruments require
additional target fixtures described in their [controller guide](../experiment/scenarios/resource_controller.md).

## Configure and start

The square avatar to the right of the header clock shows the signed-in user's initials.
It opens a separate account menu with **Minha conta** (the personal section of Preferences) and
**Sair da conta**. The tooltip and accessible label identify the account. Use Escape or click
outside to close it; keyboard users can open it with Arrow Down and navigate its actions with Tab.
Preferences is available to both roles, with separate sections for personal account access,
shared operation settings and account management. Operators can read operation settings and
change their own password. Only administrators can save shared settings or manage other accounts.
Changing your password ends all your sessions. The legacy `/contas.html` address redirects to the
personal section; the former home preferences shortcut opens the operation section.

**Preferências → Exibição** saves personal choices to your account: comfortable/compact
incident and audit rows, 10/25/50/100 initial audit records, optional remembered audit filters,
search and ordering, local/UTC dates and reduced motion. The operating system's reduced-motion
request is always respected. Save to apply, or fill the defaults and save to restore them.
These settings are separate from operational ranking and apply across browsers after login.
Audit filters use the selected timezone and always reopen on page one; the chosen initial page
size applies on each visit. Turning remembered filters off clears their saved state. Aggregate
decision charts and exports retain UTC; original evidence/output is never rewritten.

From a checkout, follow [README installation](../README.md#-getting-started). Copy `.env.example`
to `.env`, replace the database password, then initialize administrative access and use the forms
or optional environment inputs for Zabbix/SSH. Saved connections override those inputs. Inside containers,
`localhost` refers to the current container: use the existing server address or Compose service
name, not a host-only loopback URL. Database values inside the application are supplied by Compose.
Keep `.env`, private keys, dumps and evidence outside Git and image builds.

| Setting | Role |
|:--|:--|
| `ZABBIX_URL`, user/password or token | Existing monitoring API, with event/host/item read access |
| `POLARIS_WEBHOOK_TOKEN` | Shared secret in `X-Polaris-Token` on incoming events |
| `TARGET_SSH_HOST`, `TARGET_SSH_USER` | Single configured Linux remediation target/account |
| `TARGET_SSH_KEY_PATH` | Dedicated service private key on the Compose host |
| `POLARIS_ZABBIX_HOST` | Optional exact technical host name for server CPU/memory readings |
| `POLARIS_POLLING_SEGUNDOS` | Reconciliation interval; 30 seconds by default, zero disables |
| `POLARIS_CONFIDENCE_HISTORY` | Historical confidence factors; disable for controlled comparisons |
| `POLARIS_DEBUG` | Debug simulation endpoint; disable for controlled comparisons |
| `POLARIS_API_PORT`, `POLARIS_DB_PORT` | Published ports, default 8000/5432 |

Create a dedicated service key and authorize only its public half on the target `polaris` account.
Follow [secrets/README.md](../secrets/README.md) to verify host fingerprints before saving trust.
Compose runs the API as UID 1000; the mounted private file must be readable by that identity and
protected from other users. On a Linux host, inspect ownership/mode and arrange a restricted owner
or ACL. Do not solve access failures by making a private key world-readable. Windows bind mounts
require their corresponding ACL review. Keep the existing host-key verification enabled.

On the target, an administrator manually creates/configures the service account, its SSH public
key and the sudo policy. The current service transport requires this policy, edited/validated
using `visudo`:

```sudoers
polaris ALL=(root) NOPASSWD: /usr/bin/timeout
```

This grants root-capable command execution through `timeout`; it is not a per-script allowlist.
Use only a disposable, isolated target under this model. There is no automatic target installer.
Check actual binary paths/packages and permissions before testing; do not modify sudo during a round.

Both API and reconciler need the same `TARGET_SSH_HOST`, `TARGET_SSH_USER` and service key.
The default Compose shares encrypted configuration and a separate master key with both processes:
reconciliation also collects diagnostic evidence when it creates an incident. It does not execute
remediation; execution remains in the API after persisted human approval. Saved connections reload
without recreation; environment changes still require recreating both services. Optional file-based
SSH needs `-f docker-compose.yml -f compose.ssh-env.yml` on every Compose command. A missing plan disables approval and offers an explicit
**Atualizar diagnóstico** action; do not bypass it or grant approval through SQL.

Start database/API, migrate, then start reconciliation:

```bash
docker compose up -d --build polaris-db polaris-api
docker compose exec -T polaris-api python -m src.db.migrate
docker compose exec -T polaris-api python -m src.db.migrate --status
docker compose up -d polaris-reconciler
docker compose ps
```

The current schema has twelve numbered migrations. They run once with checksum verification;
never edit an applied SQL file or recreate the volume to bypass a migration problem.
Wait for API/database health before calling endpoints. A connection reset immediately after
recreation can occur during startup; a persistent failure needs logs/diagnostics.

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/api/v1/conectividade
curl -fsS http://localhost:8000/api/v1/diagnostico
curl -fsS http://localhost:8000/api/v1/reconciliacao
```

Diagnostics mask configured secrets, but contain environment/host metadata. Review before sharing.
`/health` describes API/schema/KB readiness; connectivity checks database and Zabbix separately.
The reconciler has no HTTP healthcheck: inspect its process and last cycle, not an API probe against it.

## Zabbix and host identity

Use the [template and Media Type instructions](../README.md#scalable-zabbix-onboarding).
Retain one canonical CPU trigger instead of creating a duplicate official CPU problem. In the
laboratory, the target host uses a host-level trigger `Polaris: High CPU utilization` with
expression `min(/<host>/system.cpu.util,2m)>90` and tag `polaris=enabled`, and the official
5-minute `Linux: High CPU utilization` trigger is disabled on that host only. Both use the same
metric; the shorter window reduces detection time equally in both experiment arms. The
`Linux: Load average is too high` event is not a CPU-utilization metric and stays without rule. The
companion template discovers filesystem alerts, while bundled R001 execution remains limited to
the controlled mount. Trigger discovery does not authorize arbitrary cleanup destinations.
Before every rehearsal confirm alert closure/rearming, no duplicates and synchronized clocks.
Keep the operator's Zabbix frontend refresh equal to the Polaris queue polling (3 s): set the
user profile Refresh to `3s` and follow *Monitoring → Problems* rather than a dashboard widget,
whose minimum refresh is 10 s. Otherwise the baseline arm sees the same problem later.

An IP-configured experiment target requires a matching valid incident IP. The webhook Media Type
already sends `host_ip`; reconciliation needs host/interface read permission and an unambiguous
primary IP-based agent interface. Do not change evidence, use aliases or weaken identity checks
to force a link. Old rows without an IP remain historical; validate a new event after deployment.

For server gauges only, enroll an observability host with enabled CPU-idle and memory-available
percentage items, no remediation templates/triggers. Optional gauges do not change the SSH target.

## Back up and update

Preserve **both** setup volumes, keeping the `polaris-setup-key` master-key backup separate and
access-restricted from the `polaris-setup-data` ciphertext backup. Database dumps do not include
these volumes. Stop API/reconciler during a consistent configuration backup. Never replace a
missing master key with a new file: restore the matching pair. Master-key rotation/migration
is not automated. To replace a lost or compromised administrative access code locally:

```bash
docker compose exec polaris-api python -m src.engine.setup_vault --rotate-access
```

This preserves configuration and displays a new installation code once; it does not bypass
existing accounts or rotate Zabbix tokens, SSH keys or the master key. Operational API reads and
writes now require individual login. See [accounts and recovery](access.md).

Run on the Linux collection host, from the checkout. The backup helper creates a new custom-format
dump on the host without mounting an administrative key:

```bash
python3 experiment/lab.py backup --output experiment/evidence/before-update-UNIQUE.dump
```

Replace `UNIQUE` with a new identifier. Existing destinations are refused; `.partial` is not a
completed dump. Inspect its archive catalog without restoring into the live database:

```bash
docker compose exec -T polaris-db pg_restore --list < experiment/evidence/before-update-UNIQUE.dump
```

A readable catalog does not prove a restore. Test restoration separately into a new disposable
database with matching PostgreSQL, and preserve the original dump. Never overwrite the audit
database or remove its volume as a routine update/reset. Raw backup publication is a separate
privacy/security review.

After preserving evidence and confirming a clean checkout:

```bash
git status --short
git pull --ff-only
docker compose up -d --build polaris-api polaris-reconciler
docker compose exec -T polaris-api python -m src.db.migrate
docker compose exec -T polaris-api python -m src.db.migrate --status
docker compose ps
python3 experiment/lab.py inspect
```

Record checkout SHA, each running service's immutable image ID, KB version and actual selected
configuration. A mutable image tag or `/health` version alone does not prove build provenance.
Do not update code/configuration/migrations halfway through an official comparison. A failed
checksum requires investigation; there is no automatic database downgrade.

## Read-only operational audit

Open **Tools → Auditoria**, or `/auditoria.html`, with an administrator or operator session.
Filter by creation dates, literal host/operator fragments, exact rule, current outcome/state and
human decision. Approval and execution success are separate facts. The default UI range is the
last 30 calendar dates in your selected local/UTC timezone; dates include the entire final day.
A window may cover at most 366 days. The default page contains 25 records, ordered by creation
timestamp and ID descending; personal Exibição settings can change the initial size and restore
the last successfully applied filters/search/order. Reopening starts on page one.

Select 10, 25, 50 or 100 records per page and use the numbered navigation. Click a column heading
to toggle ascending/descending order; the arrow and accessible state identify the active sort.
Sorting applies to the entire matching set, with missing values last and ID as a stable tie-breaker.
The free search updates while typing and matches literal, case-insensitive persisted values,
including commands, output, explanation and displayed decision/state labels (up to 200 characters).
Dates are searchable in their persisted UTC form and creation date as `DD/MM/YYYY`. Advanced
filters still apply; search and sorting are also applied to complete exports, before pagination.

The application header is shared with the home, account, setup and laboratory pages. Its own
connectivity/resource checks may contact Zabbix, as on the home page; audit API queries themselves
only read the database. The header never approves incidents or runs remediation automatically.

Details show persisted commands, output, errors, timestamps, versions and explanation. Historical
records are not reconstructed from today's rules. Opening them does not mark a card as displayed,
approve an action, contact Zabbix/SSH or write to the incident/experiment tables. Session activity
still updates normally. Optional remembered filters write only the user's `preferencias_exibicao`
row through its separate authenticated route. This is a live operational query, not an immutable experimental snapshot;
operational completion time is distinct from independent laboratory recovery measurements.

CSV/JSON exports include **all records matching the applied filters**, not just the current page.
Each file is limited to 500 records and 8 MiB; exceeding a limit returns an error and requires
narrower filters, without silently dropping rows or output. JSON includes filters and generation
time; dates are UTC. CSV uses UTF-8 with BOM, JSON for structured cells, and an apostrophe before
potential spreadsheet formulas. Use JSON to preserve original strings exactly. No vault or account
secrets are exported, but persisted command output can contain sensitive operational data; handle
the downloaded files according to the same access rules as incident details.

## Failures and safe stopping

| Symptom | Check/action |
|:--|:--|
| API unavailable after startup | `docker compose ps` and service logs; wait for healthy startup, inspect persistent errors |
| Database diagnostic fails | Database service/credentials/schema; never erase the volume to make it green |
| Zabbix fails or reconciliation is stale | Complete URL, authentication/permissions, interval and reconciler logs |
| SSH refused | Verified fingerprint, target/account, key readability/authorization, connectivity; do not disable strict checking |
| Approval conflict | Reload current incident/scripts; inspect existing decision instead of sending another execution |
| Incident has no rule | It is recorded coverage outside the KB; show unmatched alerts explicitly if needed |
| Round link refused | Exact IDs, target IP, KB and timestamp order; no retrospective timestamp repair |
| Controller interrupted or observation timed out | Inspect reported run ID and target; assess valid failure or discard measurement error before explicit reset |
| Reset blocked | Open round or pending/executing incident; preserve evidence and resolve through normal paths |

Use [the full laboratory workflow](../experiment/laboratorio.md) for actions that inject faults.
Do not run them unattended. Stop when the wrong target, unexpected data, clock discrepancy,
unknown host key, wrong image or ambiguous identity is found. Cleanup is separate from measured
remediation; no successful check alone establishes experimental correctness.


### Polling event evidence

The reconciliation API account also needs read access to trigger items (`trigger.get`) and item
history (`history.get`). A single item on a single event host supplies the key and the latest
historical sample at or before the event clock/ns. The current `lastvalue` is deliberately not used
for an older event. Missing history remains partial evidence; multiple items/hosts are not guessed.
Event tags still take precedence for type classification, while the actual metric key continues
to constrain rule matching. This does not authorize remediation or alter the human approval guard.
