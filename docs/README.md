# Polaris documentation

These guides describe the current implementation. Laboratory rehearsal and official measurements
are separate from automated tests; no measured performance improvement is claimed here.

- [Step-by-step installation](installation.md): ordered setup, public artifacts and the guided
  assistant (**Ferramentas → Configuração inicial**), with [validation scope](installation-validation.md).

- [Installation and operations](operations.md): configuration, SSH trust, migrations, updates,
  backup, diagnostics and failure handling.
- [Accounts and roles](access.md): first administrator, individual login, sessions, recovery and
  script acknowledgement after the frozen experiment.
- [Architecture and security boundaries](architecture.md): ingestion, human decisions,
  execution, reconciliation and the independent experiment observer.
- [Read-only diagnostics, action plans and preferences](action_plans.md).
- [Physical data model](data_model.md): actual PostgreSQL columns, constraints and derived views.
- [Diagram sources and images](diagrams/README.md): editable Mermaid, SVG and PNG exports.
- [Laboratory workflow](../experiment/laboratorio.md): check, inject, observe, link, assess,
  preserve evidence and explicitly reset.
- [Manual nginx baseline](../experiment/runbook_baseline.md) and
  [manual CPU/disk baseline](../experiment/runbook_resources.md).
- [Specific-action manual baseline](../experiment/runbook_action_plans.md) for KB 1.0.2.
- [Round registration and assessment](../experiment/rounds.md).
- [Descriptive analysis and reports](../experiment/analysis/report.md).
- [SSH key and host trust](../secrets/README.md) and [schema migrations](../src/db/migrations/README.md).

For exact dependency versions use [requirements.txt](../requirements.txt); for behavior changes
use [CHANGELOG.md](../CHANGELOG.md). `/docs` on a running API provides the generated HTTP contract.
The `/health` version, engine version, knowledge-base version, Git SHA and immutable image ID
identify different things. Preserve all of them when reproducing a deployment.
