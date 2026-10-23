# Installation and operations

For a first installation, start with [the ordered installation guide](installation.md).
The in-app assistant at `/configuracao.html` tests and saves encrypted connections. It does not
provision external services. This reference covers ongoing operation and troubleshooting.

The supported controlled target is Ubuntu 24.04 LTS with systemd and nginx. Polaris runs through
Docker Compose; an existing Zabbix 7.0 LTS instance can be reused. The optional `zabbix` profile
is for an isolated installation, not a second production monitor. CPU/disk instruments require
additional target fixtures described in their [controller guide](../experiment/scenarios/resource_controller.md).

## Configure and start

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

The current schema has ten numbered migrations. They run once with checksum verification;
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

This preserves configuration, displays a new code once and revokes old sessions; it does not
rotate Zabbix tokens, SSH keys or the master key. Shared code/session access is not per-operator
authentication. GET operational API routes remain readable within the trusted network.

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
