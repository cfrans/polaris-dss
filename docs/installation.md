# Install Polaris, step by step

This is the installation path for the guided-setup development version after
`v1.0.3-experimento`. The experiment tag and its measurements remain unchanged.
The web assistant is available at **Tools → Configuração inicial** or `/configuracao.html`.
It provides forms, connection tests, encrypted configuration and public downloads. Zabbix and
SSH connections can be entered in the browser; environment-based configuration remains optional.
This guide remains usable when the API cannot start.

## 1. Choose the environment

Use Docker Engine with Compose v2 and Git on a dedicated Linux host, or Docker Desktop with
Linux containers on Windows/macOS. Linux is the reference deployment host. Commands below are
run from the repository root. On Windows use PowerShell; on Linux/macOS use a shell such as Bash.

You need a Zabbix **7.0 LTS** server reachable from the application containers, plus one
explicitly configured Ubuntu **24.04 LTS** target with SSH and systemd if you want real remediation.
An existing Zabbix is preferred; the optional Compose profile is for a separate laboratory.
The default stack publishes API 8000 and database 5432; make sure those ports and the fixed
container names `polaris-api`/`polaris-db` are free. A different Compose project name alone does
not override these fixed names. Do not run a second copy over an existing installation.

```bash
git clone https://github.com/cfrans/polaris-dss.git
cd polaris-dss
docker version
docker compose version
```

For reproduction of the original experiment, check out `v1.0.3-experimento` in a separate
directory and use its own instructions. Do not update a preserved collection environment.

**Boundary:** this prototype uses [individual local accounts](access.md); its SSH service credential is capable
of root execution. Use an isolated, access-controlled environment and a disposable target.
Do not expose the API or PostgreSQL to the Internet. A successful setup check is not a
production-readiness or security certification. See [security boundaries](architecture.md#security-scope).

## 2. Bootstrap Docker and the audit database

Copy the example once. Do not overwrite an existing `.env` during an update.

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally to replace the database password and select free published ports. The database
must exist before the assistant can operate; it cannot change its own database credentials.
Clear example Zabbix credentials if you will use the forms. Keep private values outside Git,
screenshots and support messages. Zabbix, webhook, target and polling values below are optional
environment inputs; tested values saved by the assistant take precedence.

| Variable | What to set |
|:--|:--|
| `DB_PASSWORD` | A unique database password; changing this variable does not rotate a password in an existing PostgreSQL volume |
| `ZABBIX_URL` | Full API address, for example `https://monitor.example/api_jsonrpc.php` |
| `ZABBIX_TOKEN` | API token for a dedicated Zabbix account with access to the monitored host group |
| `ZABBIX_USER` / `ZABBIX_PASSWORD` | Alternative to a token; clear the example values when using a token |
| `POLARIS_WEBHOOK_TOKEN` | A distinct random secret, also configured in the Zabbix Media Type |
| `TARGET_SSH_HOST` | Single remediation target; the assistant accepts a literal IPv4/IPv6 address |
| `TARGET_SSH_USER` | Target service account, normally `polaris` |
| `TARGET_SSH_KEY_PATH` | Optional host private-key path, used only with `compose.ssh-env.yml` |
| `POLARIS_POLLING_SEGUNDOS` | Reconciliation interval, normally 30; zero disables the loop |
| `POLARIS_DEBUG` | Keep `false`; setup does not require alert injection |
| `POLARIS_API_PORT` / `POLARIS_DB_PORT` | Free host ports, normally 8000/5432 |

Do not use `localhost` to reach another machine from inside a container. For an existing Zabbix,
use its reachable address. For the optional profile, use `http://zabbix-web:8080/api_jsonrpc.php`.
Inside Compose the application uses `polaris-db:5432`; `DB_HOST`/`DB_PORT` are for tools run on
the host. If host tools use a different published DB port, adjust their `DB_PORT` too.
Keep `POLARIS_CONFIDENCE_HISTORY` appropriate to normal operation; disabling history and
setting experimental timings belong to the experiment protocol, not the common setup.

## 3. Start and unlock the assistant

```bash
docker compose config --quiet
docker compose up -d --build polaris-db polaris-api
docker compose exec -T polaris-api python -m src.db.migrate
docker compose exec -T polaris-api python -m src.db.migrate --status
docker compose exec polaris-api python -m src.engine.setup_vault
```

There are eleven numbered migrations. Repeating migration after success applies nothing. Never edit
applied migrations or erase a volume to fix a checksum/password error. API health may fail until
the schema is current. The last command initializes the encrypted vault once and displays a strong
administrative code **once**. Store it in a password manager; an existing vault is never overwritten.

Open `http://localhost:8000/login.html` (adjust the published port). Create the first administrator
with the installation code, then sign in with your account. Administrators can open the wizard. HTTP credential entry is accepted only on loopback; access through another address requires
HTTPS with a trusted TLS terminator. The session uses an HttpOnly/SameSite cookie and expires
after 15 idle minutes or eight hours. Sessions are persisted in PostgreSQL. Sign in before using the operational API. Decisions use the session identity. The installation
code cannot bypass account login; neither login nor script acknowledgement replaces incident approval.

Compose stores `configuration.enc` in `polaris-setup-data` and its master key in the separate
`polaris-setup-key` volume. Both persist across container recreation; the reconciler receives
read-only mounts. Do not remove either volume. Losing the key makes the configuration unreadable;
possessing both permits decryption. Back them up separately with restricted access. The two
`POLARIS_SETUP_*` paths are supplied by Compose; custom paths require matching mounts.

The default Compose needs no SSH placeholder files. DB/schema/KB can pass without a configured
target, but later steps stay blocked. This is a partial installation, not end-to-end acceptance.

## 4. Configure connections in the browser

In the Zabbix step, enter its URL and either an API token or dedicated username/password. Generate
or enter a separate reception token (at least 24 characters). Copy a new reception token into the
Zabbix Media Type before saving: saved secrets are never returned by the API. **Testar conexão**
checks Zabbix 7.0 and an authenticated host query. **Salvar conexão testada** becomes available
only after success. The test expires after five minutes; editing, failure, another configuration
revision or saving consumes/invalidates it. A successful API query does not prove every permission
or event delivery. Complete the manual integration in section 6.

**Carregar do ambiente** fills public fields and indicates whether secrets are available on the
server. Empty secret fields reuse that selected source; they are never prefilled with the secret.
Test and save to copy the effective connection into the encrypted vault. Existing `.env` secrets
are not retroactively encrypted: remove migrated values yourself only after verifying operation.

For SSH, enter the target IP/account and generate a dedicated key. Only its public half is shown;
the private half is encrypted on the server. Authorize the public line on the target as below.
Use **Consultar identidade pela rede**, then independently obtain the fingerprint directly on
the target. Enter that trusted fingerprint; the application never automatically trusts a scanned
key. **Testar acesso SSH** verifies the pin, authenticates and executes only `true`. Save after
success. Unknown or changed host keys are rejected. This test does not verify sudo privileges.

Changes to active connections/polling are refused while any incident is pending or executing, or
when the database cannot establish that no such incident exists. API operations and reconciler
cycles share a process lock with setup writes. Resolve incidents through their normal workflow;
do not change rows to bypass the guard. If another operation/configuration intervenes, test again.

### Target preparation and optional environment key

For a real target, an administrator creates a dedicated account on that Ubuntu target:

```bash
sudo adduser --disabled-password --gecos '' polaris
sudo install -d -m 0700 -o polaris -g polaris /home/polaris/.ssh
```

For the browser path, append only the generated public line to the target account's
`authorized_keys`, with owner `polaris:polaris` and mode `0600`. Nothing private goes to the target.

For the optional environment/file path, generate a **new service key** on the Docker host. Never reuse your
personal or administrative private key. Do not regenerate or overwrite an existing service key.
The `secrets` directory already exists in the checkout.

```bash
ssh-keygen -t ed25519 -N "" -f secrets/polaris_ed25519 -C polaris-dss
```

Some PowerShell/OpenSSH versions handle empty quoted arguments differently: if `-N ""`
is rejected, run without `-N` and press Enter at both passphrase prompts for this dedicated
unattended service key. Authorize **only** `secrets/polaris_ed25519.pub` on the target by appending
that public line to `/home/polaris/.ssh/authorized_keys`, then set owner `polaris:polaris` and
mode `0600` on that file. Do not copy the private half to the target.

Obtain the target's public SSH host key using `ssh-keyscan -t ed25519 <target-ip>`.
Compare its fingerprint (`ssh-keygen -lf <scanned-file>`) with the fingerprint read directly
on the target using `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Only after they agree,
save the scanned line to `secrets/known_hosts` as UTF-8 text. Unknown/changed keys are rejected.
Never disable host-key checking to finish setup.

On a Linux Docker host, the service runs as UID/GID 1000. Grant that identity read access to
the dedicated private file with owner `1000:1000`, mode `0600`, or an equivalent restricted ACL.
For the default dedicated file on Linux:

```bash
sudo chown 1000:1000 secrets/polaris_ed25519
sudo chmod 0600 secrets/polaris_ed25519
```

On Docker Desktop, review the host file ACL and test readability inside the container rather
than assuming Linux ownership commands apply to the host. Keep the file restricted to its owner.

On the disposable target, an administrator uses `sudo visudo -f /etc/sudoers.d/polaris` to add:

```sudoers
polaris ALL=(root) NOPASSWD: /usr/bin/timeout
```

Validate with `sudo visudo -cf /etc/sudoers.d/polaris`. This policy allows arbitrary commands
under `timeout` as root; it is **not** a per-script restriction. SSH connection success does
not verify this policy. Do not apply it to a production host as a generic installer step.
Scripts stay central in Polaris; do not install a remediation-script directory on the target.

Only the environment/file path needs both regular files before mounting. Add the optional
Compose file to **every** operation for that installation, including later updates:

```bash
docker compose -f docker-compose.yml -f compose.ssh-env.yml config --quiet
docker compose -f docker-compose.yml -f compose.ssh-env.yml up -d polaris-api polaris-reconciler
```

The API sees the file at `/run/secrets/polaris_ssh_key`; never mount the operator's SSH directory.
The default browser path requires neither this override nor files under `secrets/`.

## 6. Complete the Zabbix integration manually

In Zabbix 7.0, create a dedicated API identity with host-group read access. Enable the API role
methods required for `host.get`, `event.get`, `problem.get`, `trigger.get`, `item.get` and
`history.get`; authentication also uses `apiinfo.version` and optionally `user.login`.
Token accepted by the API does not establish every required permission. Expiry and host-group
access must be checked in Zabbix too.

1. Import `infra/zabbix/polaris-template-linux.yaml` under **Data collection → Templates**.
   Link **Polaris DSS Linux** together with the official **Linux by Zabbix agent** template
   to the intended Ubuntu host. Ensure its agent, interface and actual service are configured.
2. Import `infra/zabbix/polaris-mediatype.yaml` under **Alerts → Media types**. Replace the
   example `polaris_url` with the URL reachable **from the Zabbix server**, ending in
   `/webhook/zabbix`; set `polaris_token` to the local `POLARIS_WEBHOOK_TOKEN`. Do not change
   the Media Type's event macros to literal values. No secrets belong in the versioned YAML.
3. Add this media to the chosen Zabbix notification user, with an active period/severities
   covering the events. Verify that the user has permission to receive the relevant events.
4. Create an enabled **Trigger action** with a send-message operation to that user and Media
   Type. Use custom expression `(A and B) or (C and D)`: A = tag name `polaris`; B = tag
   `polaris` value `enabled`; C = template **Linux by Zabbix agent**; D = event name contains
   `Linux: High CPU utilization`. These correspond to the bundled templates, not arbitrary alerts.
5. Review the host templates, enabled items/triggers and latest values. Do not duplicate CPU
   triggers. The shorter CPU trigger used in the original controlled laboratory is a separate
   experiment configuration; this installer does not change trigger windows or thresholds.

The assistant downloads the **installed** template, Media Type and example configuration.
It cannot verify all manual Zabbix steps. Checking a confirmation records only your acknowledgement
for this visit; it is not a server audit record and is reset when you reload the page.

R001 can discover filesystem events, but its bundled cleanup policy is restricted to
`/mnt/polaris_test`. Do not create or fill this volume during normal installation. A Zabbix host
being monitored does not become an authorized SSH destination automatically.

## 7. Start reconciliation and review

After configuring Zabbix, start the separate reconciler:

```bash
docker compose up -d polaris-reconciler
docker compose ps
```

Set the polling interval in the assistant (5–3600 seconds, or zero to pause). The running reconciler reads saved
configuration on its next cycle, including activation from an environment interval of zero.
Browser-saved connections require no container recreation. Changes to environment values still
require recreating **both** API and reconciler from the same image:

```bash
docker compose up -d --build polaris-api polaris-reconciler
```

Run the assistant check again. A recent successful reconciliation cycle verifies polling,
not delivery of webhook notifications. A configured token does not prove successful delivery
either. Final acceptance requires an administrator to check the Zabbix action log and match a
known, authorized event to its Polaris incident. This guide does not inject incidents or approve
remediation. Any controlled end-to-end exercise is a separate, explicitly operated procedure.

Review **Scripts e ciência**, actual target identity, sudo scope, network access and backup
procedure before approving any real incident. The original experiment results apply only to
the frozen version; no new performance result is claimed by this installation feature.

## Troubleshooting and updates

| Symptom | Next check |
|:--|:--|
| Docker cannot connect | Start Docker Engine/Desktop; verify Linux containers and local access permissions |
| Port/name already allocated | Inspect existing services; use another host or a deliberate Compose override; do not delete unrelated containers |
| Private-key path became a directory | Stop this installation; fix the source to a regular file before recreating services |
| Database or schema check fails | Inspect DB health/credentials, then migrate; preserve the volume |
| Zabbix pending/fails | Complete JSON-RPC URL, container network access, credentials, API role and host-group permissions |
| SSH check fails | Target/account, public-key authorization, private-file readability and verified host fingerprint |
| Reconciliation is waiting/stale | Start its process; inspect its logs and Zabbix access; run a fresh check |
| All dependency checks pass, no events arrive | Check Media Type, recipient media/permissions and enabled Action; connectivity is not event-delivery proof |
| API cannot start | Read this guide from Git; inspect `docker compose logs --tail 80 polaris-api` locally without sharing secrets |

For backups, safe updates and failure handling see [operations](operations.md). Keep `.env`,
private keys, database dumps and raw evidence outside Git. Never remove a volume as a routine
update. Record the checkout SHA, immutable image IDs and actual configuration when reproducing
an installation. See [validation scope](installation-validation.md) for what has been tested.

Reference documentation: [Docker Compose configuration validation](https://docs.docker.com/reference/cli/docker/compose/config/),
[Zabbix 7.0 webhook media](https://www.zabbix.com/documentation/7.0/en/manual/config/notifications/media/webhook).
