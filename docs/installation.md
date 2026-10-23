# Install Polaris, step by step

This is the installation path for the guided-setup development version after
`v1.0.3-experimento`. The experiment tag and its measurements remain unchanged.
The web assistant is available at **Tools → Configuração inicial** or `/configuracao.html`.
It provides instructions, public downloads and read-only checks; it does not change configuration.
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

**Boundary:** this prototype has no operator login and its SSH service credential is capable
of root execution. Use an isolated, access-controlled environment and a disposable target.
Do not expose the API or PostgreSQL to the Internet. A successful setup check is not a
production-readiness or security certification. See [security boundaries](architecture.md#security-scope).

## 2. Configure the application

Copy the example once. Do not overwrite an existing `.env` during an update.

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` locally. Replace the example database password, Zabbix credentials and webhook
token before starting. Keep all private values outside Git, screenshots and support messages.

| Variable | What to set |
|:--|:--|
| `DB_PASSWORD` | A unique database password; changing this variable does not rotate a password in an existing PostgreSQL volume |
| `ZABBIX_URL` | Full API address, for example `https://monitor.example/api_jsonrpc.php` |
| `ZABBIX_TOKEN` | API token for a dedicated Zabbix account with access to the monitored host group |
| `ZABBIX_USER` / `ZABBIX_PASSWORD` | Alternative to a token; clear the example values when using a token |
| `POLARIS_WEBHOOK_TOKEN` | A distinct random secret, also configured in the Zabbix Media Type |
| `TARGET_SSH_HOST` | IP or name of the single remediation target; leave empty for simulated execution only |
| `TARGET_SSH_USER` | Target service account, normally `polaris` |
| `TARGET_SSH_KEY_PATH` | Host path to the dedicated service private key, normally `./secrets/polaris_ed25519` |
| `POLARIS_POLLING_SEGUNDOS` | Reconciliation interval, normally 30; zero disables the loop |
| `POLARIS_DEBUG` | Keep `false`; setup does not require alert injection |
| `POLARIS_API_PORT` / `POLARIS_DB_PORT` | Free host ports, normally 8000/5432 |

Do not use `localhost` to reach another machine from inside a container. For an existing Zabbix,
use its reachable address. For the optional profile, use `http://zabbix-web:8080/api_jsonrpc.php`.
Inside Compose the application uses `polaris-db:5432`; `DB_HOST`/`DB_PORT` are for tools run on
the host. If host tools use a different published DB port, adjust their `DB_PORT` too.
Keep `POLARIS_CONFIDENCE_HISTORY` appropriate to normal operation; disabling history and
setting experimental timings belong to the experiment protocol, not the common setup.

## 3. Prepare SSH trust before mounting files

For a real target, an administrator creates a dedicated account on that Ubuntu target:

```bash
sudo adduser --disabled-password --gecos '' polaris
sudo install -d -m 0700 -o polaris -g polaris /home/polaris/.ssh
```

Generate a **new service key**, from the repository root on the Docker host. Never reuse your
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

For a local interface-only installation with **no target**, leave `TARGET_SSH_HOST` empty.
Compose still requires regular source files for both bind mounts. Create empty placeholder
files at `secrets/polaris_ed25519` and `secrets/known_hosts` **only if absent**. These placeholders
are not credentials and SSH must remain unconfigured. Replace them through the real trust
procedure before configuring a real target. A missing source may otherwise become a directory.

For this no-target option, create only missing files on Linux/macOS:

```bash
for file in secrets/polaris_ed25519 secrets/known_hosts; do
  if [ ! -e "$file" ]; then (umask 077; touch "$file"); fi
done
```

Or on Windows PowerShell:

```powershell
foreach ($setupFile in @('secrets/polaris_ed25519', 'secrets/known_hosts')) {
  if (-not (Test-Path -LiteralPath $setupFile)) {
    New-Item -ItemType File -Path $setupFile | Out-Null
  }
}
```

## 4. Start the services in order

Validate Compose syntax without printing the resolved configuration, which may contain secrets:

```bash
docker compose config --quiet
docker compose up -d --build polaris-db polaris-api
docker compose exec -T polaris-api python -m src.db.migrate
docker compose exec -T polaris-api python -m src.db.migrate --status
docker compose ps
```

There are ten numbered migrations. The application must reach the empty database before they
can be applied; API health can be unhealthy until migration completes. Re-running the migrate
command after success applies nothing. Never edit applied migrations or erase a volume to fix
a checksum error. A database password mismatch on an old volume is not fixed by migration.

Open `http://localhost:8000/configuracao.html` (substitute the published API port). Use
**Verificar conexões** after making changes. The assistant reads dependencies on demand,
including an SSH `true` command if a real target is configured. It performs no remediation.
For the no-target installation, database/schema/KB can pass while SSH and Zabbix stay pending.
That is a partial installation, not an end-to-end success.

## 5. Connect Zabbix manually

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

## 6. Start reconciliation and review

After configuring Zabbix, start the separate reconciler:

```bash
docker compose up -d polaris-reconciler
docker compose ps
```

If configuration changed after startup, recreate **both** API and reconciler from the same image:

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
