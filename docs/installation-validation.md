# Installation validation scope

The guided assistant belongs to development **1.1.0-dev**, after the frozen experiment.
Its checks do not constitute a new performance evaluation or production certification.

## Local validation — 22 October 2026

The initial installation path was exercised on Windows with Docker Engine 29.7.2, using a
separate Compose project, new PostgreSQL volume, loopback-only ports, dedicated image tag
and empty SSH placeholders. No real configuration file, target, monitoring credentials or
collection database was used. Application runtime: Python 3.12.15, PostgreSQL 16 image.

| Area | Scope |
|:--|:--|
| Container installation | Image built from the development source; database and API started separately |
| Clean published checkout | Commit `4b5d098` cloned from GitHub, separate second project/volume, example copied and no-target files prepared; syntax/build/start/migrations passed; all four HTTP downloads matched the clone byte for byte |
| Schema | Ten migrations applied to an empty database; repeated migration applied nothing; status had no pending migration |
| Partial configuration | Database/schema/KB checks pass; missing SSH/Zabbix and disabled reconciliation remain pending |
| Artifact downloads | Exact installed bytes for guide/example/template/Media Type; unknown identifiers and file traversal rejected; no database dependency |
| Frontend behavior | Six steps, command copying, explicit checks, manual acknowledgement separation, stale/failure states, desktop and 390 px layout |
| Regression suite | 609 Python tests passed, six skipped optional graphics/root cases; 49 JavaScript tests passed in Node 22.23.4/Linux |

The production Docker image deliberately omits `experiment/analysis/` and Git metadata.
The full Python regression suite was run in a temporary test container with those **source**
paths mounted read-only, history enabled and polling set to the test defaults. That does not
enable a running reconciler or inject faults. The installed demonstration API kept no target,
no Zabbix credentials and polling disabled. The Windows Bash-dependent JavaScript regression
was verified in the Linux Node image instead of changing the test to ignore the failure.

## External/manual acceptance still required

This local validation does not repeat the existing laboratory's real SSH remediation or
reconfigure its Zabbix. A new installation still requires its administrator to:

- compare the real target fingerprint and review service-account privileges;
- verify the Zabbix API role and monitored host-group permissions;
- import/link templates, recipient media and the enabled Action;
- inspect an authorized event's delivery and its corresponding Polaris incident;
- verify target-specific packages/paths, network exposure and backup/restore procedure.

The assistant explicitly asks for these confirmations and does not label them automatically
verified. Successful SSH `true`, an authenticated API read and a successful polling cycle
verify separate connections; none establishes successful notification delivery or remedy.
Windows/macOS host ACL differences and a clean Zabbix deployment are not certified by the
local no-target run. The original experiment and its preserved version remain distinct.
