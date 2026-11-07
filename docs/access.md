# Accounts and access

Individual login belongs to development 1.1.0-dev, after the frozen experiment. It does not
retroactively authenticate historical operator labels or change the experiment's results.

## First administrator

Start the database/API, apply all **thirteen** migrations and initialize the vault using the
[installation guide](installation.md). Open `/login.html`. With no accounts, it asks for the
installation code, your name, a unique lowercase username and a 15–128 character passphrase.
The code comes from `python -m src.engine.setup_vault` in the container; no default account exists.
Bootstrap is serialized in the database and closes once the first account exists. An old shared
setup code can no longer unlock application sessions or make incident decisions. After the first
administrator is created, the browser continues directly to the setup wizard.

The first account is an administrator. After signing in, **Preferências → Gestão de contas** lets an
administrator create administrator/operator accounts and deactivate other accounts. Usernames
are immutable and accounts are retained for historical attribution; self-deactivation is refused.
The administrator must share initial credentials privately. There is no public signup, email
invitation or recovery service. Users may change their own password after entering the current
one; all of their sessions then end. An administrator with local server access can recover a
password interactively, without putting it in arguments or environment variables:

```bash
docker compose exec polaris-api python -m src.api.auth --reset-password username
```

This preserves account role/active status and revokes its sessions. `--rotate-access` in the
vault command rotates only the first-installation code; it does not bypass an existing login.

The initials avatar after the header clock opens **Minha conta** and **Sair da conta**. Personal
display choices are under **Preferências → Exibição** and are available to both roles. They are
stored by authenticated user in PostgreSQL, not in browser storage. Compact density, initial
audit page size, optional remembered filters, local/UTC presentation and reduced motion do not
change operational ranking, measurements or permission checks. Turning remembered filters off
erases the saved filter state; exports and aggregated decision charts retain their original UTC
semantics. See [operations](operations.md).

## Roles and sessions

- Both roles can read operational data, acknowledge scripts and explicitly approve/reject incidents.
- Only administrators configure integrations, reload rules, change global preferences, use debug
  simulation and administer accounts. A role cannot be chosen in the decision request.
- Operational API routes require authentication, including reads. `/health`, static login assets,
  API schema and allowlisted public installation downloads remain public. Webhook ingestion keeps
  its separate monitoring token; the reconciler uses service configuration, not browser cookies.

Passwords are stored as salted Argon2id hashes (19 MiB, two passes, one lane), never encrypted
recoverable passwords. Sessions are random opaque tokens, only their SHA-256 hashes are stored
in PostgreSQL. Cookies are HttpOnly/SameSite Strict, Secure on HTTPS. Sessions expire after
15 idle minutes or eight hours; five concurrent sessions per account are retained. Login/bootstrap
share a database-backed limit of 20 attempts per minute across API workers. Errors do not distinguish
unknown usernames from wrong passwords. Logout, deactivation and password change revoke sessions.
HTTPS is required outside localhost/loopback, with trusted proxy configuration when terminating TLS,
unless the optional laboratory pairing below is enabled.
This is a local-account feature, without MFA, SSO or external identity verification.

## Network access

Polaris usually runs on a server or VM that is not the computer with the browser. Passwords,
session cookies and integration secrets must not cross the network in clear text, so plain HTTP
is accepted only on the loopback address. Choose one of three paths:

1. **SSH tunnel (default).** Keep `POLARIS_PAREAMENTO_HTTP=false`. On your computer, open a tunnel
   and keep that terminal open, then use the local address:

   ```bash
   ssh -N -L 8000:localhost:8000 your-user@SERVER-IP
   ```

   Open `http://localhost:8000/login.html`. The first port is local to your computer; change it if
   8000 is busy there. The second port is `POLARIS_API_PORT` on the server. `setup_vault` prints
   this command with the server address when given `--address` (and `--ssh-user`), and the login
   page shows it when opened by a network address.
2. **HTTPS.** Publish Polaris behind a TLS terminator trusted by your browsers. HTTPS needs no
   tunnel and no pairing. Configure the proxy to preserve the original scheme and host.
3. **HTTP pairing, isolated laboratory only.** Set `POLARIS_PAREAMENTO_HTTP=true` in `.env` and
   recreate the API (`docker compose up -d polaris-api`). A browser that opens
   `http://SERVER-IP:8000/` is then asked for a pairing code generated on the server terminal:

   ```bash
   docker compose exec polaris-api python -m src.engine.pairing --address SERVER-IP
   ```

   The code has eight characters from an unambiguous alphabet, is valid once for ten minutes and is
   stored only as a SHA-256 hash. Redeeming it gives that browser its own random HttpOnly,
   SameSite Strict cookie, valid for seven days; login and individual sessions are still required
   afterwards. Redemption shares the 20 attempts per minute limit with login.
   `python -m src.engine.pairing --revoke` removes every paired browser and pending code.
   Setting the variable back to `false` and recreating the API makes existing pairings ineffective.

**What pairing does not do.** It proves that someone with shell access to the server allowed that
browser. It does **not** encrypt the connection: anyone able to observe the network can still read
passwords, session cookies, Zabbix credentials and tokens typed in the wizard. Use it only on an
isolated laboratory network with no untrusted hosts, never on a shared or production network.
The Clipboard API is unavailable on plain HTTP, so copy buttons fall back to a temporary selection.
Pairing changes neither roles nor the persisted human approval required for every remediation.

The transport rule reads the scheme and host of the request. A client that forges `Host:
localhost` only bypasses the protection of its own credentials; it still needs a valid account.

## Decisions and script acknowledgement

The server takes the immutable username from the validated session for **both** approvals and
rejections. The optional legacy `operador` request field is ignored; it cannot spoof attribution.
Before approving, users acknowledge the current script catalog hash. That acknowledgement and
its timestamp are stored per account; local browser preferences cannot substitute for it. An
updated catalog requires a new acknowledgement. This records a confirmation, not proof that a
person read every line. General acknowledgement never approves an incident: persisted human
decision, chosen action, script hash and execution guards remain mandatory.

Do not upgrade the preserved experiment installation to exercise accounts. Use a separate
installation with new database/vault volumes for practical acceptance. Local automated tests
exercise PostgreSQL sessions, role refusals, forged operator labels and approval guards; this does
not certify a fresh external Zabbix/Ubuntu deployment. See [validation scope](installation-validation.md).

References: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
