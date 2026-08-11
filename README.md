# ⭐ Polaris DSS

### Decision Support System for IT Infrastructure Incident Remediation

> A rule-based Expert System that transforms raw monitoring alerts into actionable, human-approved remediations — reducing Mean Time To Repair while maintaining full operational governance.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Zabbix 7.0](https://img.shields.io/badge/Zabbix-7.0_LTS-D32F2F?logo=zabbix&logoColor=white)](https://www.zabbix.com)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16+-336791?logo=postgresql&logoColor=white)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📖 About

**Polaris DSS** is a lightweight, open-source **Symbolic AI** system designed for IT infrastructure incident management. Instead of using opaque Machine Learning models ("black boxes"), Polaris relies on **deterministic, explainable heuristic rules** stored in a JSON knowledge base.

The system implements a **Human-in-the-Loop (HITL)** workflow with **One-Click Repair**: when an incident is detected, Polaris analyzes it against known patterns, calculates a confidence score, and presents a remediation suggestion to the operator — who then approves or rejects with a single click.

> *The name "Polaris" references the North Star, which has historically guided navigators through uncertainty — much like this system guides IT operators through incident resolution.*

### What Polaris is NOT

- ❌ Not a Machine Learning / Deep Learning model
- ❌ Not a statistical "black box" trained on massive datasets  
- ❌ Not a blind automation tool that replaces human judgment

---

## 🏗️ Architecture

The system is organized into **three layers**:

```
┌─────────────────────────────────────────────────────┐
│              TELEMETRY LAYER (Zabbix)                │
│  Infrastructure → Metrics/Logs → Zabbix Server      │
│                    → API REST (JSON)                 │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│          INTELLIGENCE LAYER (Python)                 │
│  ┌──────────────┐  ┌─────────────────────────┐      │
│  │ Knowledge    │──│  Inference Engine        │      │
│  │ Base (JSON)  │  │  • Regex Parsing         │      │
│  └──────────────┘  │  • Rule Matching         │      │
│                    │  • Confidence Calculation │      │
│                    └────────────┬────────────┘      │
│                                 ▼                    │
│                    Remediation Suggestion             │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│       INTERFACE & AUDIT LAYER (Web + PostgreSQL)     │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐   │
│  │ Web HITL │───▶│ Operator │───▶│ Remediation  │   │
│  │ Interface│    │ Decision │    │ Execution    │   │
│  └──────────┘    └──────────┘    └──────┬───────┘   │
│                                         ▼            │
│                              ┌──────────────────┐   │
│                              │  PostgreSQL Audit │   │
│                              │  (JSONB + MTTR)   │   │
│                              └──────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Workflow

1. **Zabbix** detects an incident and sends an alert via API
2. **Inference Engine** matches the alert against heuristic rules using regex
3. **Confidence score** is calculated based on rule parameters
4. **Web interface** presents the suggestion with full diagnosis and justification
5. **Operator** reviews and approves (or rejects) with one click
6. **System executes** the remediation script on the target infrastructure
7. **Audit log** records the full incident lifecycle with timestamps for MTTR calculation

---

## ✨ Features

| Feature | Description |
|:--------|:------------|
| **Explainable AI (XAI)** | Every suggestion comes with a human-readable diagnosis and justification |
| **Human-in-the-Loop** | No action is ever executed without explicit human approval |
| **One-Click Repair** | Complex multi-step remediation reduced to a single approval click |
| **Deterministic Logic** | Same input always produces the same output — fully auditable |
| **Comprehensive Audit** | Every incident, decision, and result logged with precise timestamps |
| **MTTR Tracking** | Automatic calculation of Mean Time To Repair per incident type |
| **Lightweight** | No ML training required — runs on minimal infrastructure |

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|:------|:-----------|:--------|
| Backend | Python 3.12+ / FastAPI | Inference engine + REST API |
| Monitoring | Zabbix 7.0 LTS | Telemetry & alert detection |
| Database | PostgreSQL 16+ (JSONB) | Audit logging & MTTR tracking |
| Frontend | HTML / CSS / JavaScript | HITL web interface |
| Infrastructure | Docker Compose (Debian 12 base) | Containerized API & DB services (`python:3.12-slim`) |
| Knowledge Base | JSON | Heuristic rules storage |

---

## 🚀 Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [Python 3.12+](https://www.python.org/downloads/) (for local development)

### Installation

```bash
# Clone the repository
git clone https://github.com/cfrans/polaris-dss.git
cd polaris-dss

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# Start the Polaris audit database
docker compose up -d

# Install Python dependencies
pip install -r requirements.txt

# Apply the database schema
python -m src.db.migrate
```

The schema is managed as versioned migrations, applied once each and recorded with their checksum —
see [`src/db/migrations/README.md`](src/db/migrations/README.md). Run `python -m src.db.migrate`
after pulling changes; it is a no-op when there is nothing pending.

### Zabbix is optional

Polaris is designed as an **intelligence layer on top of monitoring you already run**. If you have a
Zabbix server, don't start another one — just point Polaris at it via `ZABBIX_URL` in `.env`.

If you need a local Zabbix for testing, it ships in an opt-in Compose profile:

```bash
docker compose --profile zabbix up -d    # adds Zabbix Server, Web and Agent, with its own database
```

> **Note on the remediation target.** Polaris and PostgreSQL run fine in containers, but the *host
> being remediated* should be a real Linux VM: a stock container has no `systemd` (so service
> restarts fail), filling a container's disk fills the host's disk, and process control inside a
> container acts on the wrong namespace.

### Running the inference engine standalone

The engine is a pure module: it needs neither Zabbix, nor a database, nor the web interface. You can
feed it an alert and read the full explained suggestion straight from the terminal — useful for
authoring rules and for understanding what the system does before deploying anything.

```bash
python -m src.engine.cli src/tests/fixtures/disk_full.json

# Full explainability trace as JSON (this is what gets stored in the audit log)
python -m src.engine.cli src/tests/fixtures/cpu_high.json --json

# Simulate audit history to exercise the rule-history and recurrence factors:
# 14 past executions, 14 successful, 2 recent recurrences on this host
python -m src.engine.cli src/tests/fixtures/service_down.json --historico 14 14 2
```

That last one is worth running: the recurrence factor drops confidence from 92% to 55%, and the
system stops recommending the restart — it reports that the previous remediation did not hold and
that the root cause is likely different from the one diagnosed.

```bash
pytest
```

### Running a full incident cycle against the database

With the database up, you can exercise the entire lifecycle — ingestion, display, human decision,
execution and completion — with a simulated executor, before any target machine exists:

```bash
python -m src.db.ciclo                  # full cycle: ingest, display, approve, execute
python -m src.db.ciclo --rejeitar       # rejection path
python -m src.db.ciclo --sem-aprovacao  # verifies that execution without approval is refused
```

The last one matters most: it proves the system's core invariant. Before executing anything, the
service re-reads the recorded approval from the database and refuses to act without it — it does not
trust the caller's word that a human approved.

### The Human-in-the-Loop interface

```bash
uvicorn src.api.server:app --reload --port 8000
# http://localhost:8000       operator interface
# http://localhost:8000/docs  interactive API documentation
```

Set `POLARIS_DEBUG=true` in `.env` to enable the **Simulate incident** button, which injects alerts
without Zabbix — enough to exercise the whole system before any monitoring is wired up.

The incident card shows the confidence band, the diagnosis, **the evidence that triggered the
rule**, and **every factor that discounted the confidence, each with its reason**. That is the
explainability claim made concrete: the trace reaches the operator as readable text, not as a JSON
blob hidden behind a toggle.

A low confidence band does not offer one-click approval — it shows a warning and requires a second
confirmation. A recurring incident gets its own warning recommending manual investigation instead of
reapplying the same fix. No band ever executes on its own.

### Running the full stack

```bash
# Start the Polaris API server
uvicorn src.api.server:app --reload --port 8000

# Access:
# - Polaris HITL Interface: http://localhost:8000
# - API docs (Swagger):     http://localhost:8000/docs
# - Zabbix Web Frontend:    http://localhost:8080 (only with the `zabbix` profile — Admin/zabbix)
```

---

## 📁 Project Structure

```
polaris-dss/
├── src/
│   ├── engine/                 # Inference engine (Python)
│   │   ├── __init__.py
│   │   ├── config.py           # Settings via environment variables
│   │   ├── inference.py        # Rule matching & regex parsing
│   │   ├── confidence.py       # Confidence score calculation
│   │   ├── zabbix_client.py    # Zabbix API integration
│   │   └── remediation.py      # Remote command execution
│   ├── knowledge_base/         # Heuristic rules (JSON)
│   │   ├── rules.json          # If-Then rules with conditions & actions
│   │   └── schema.json         # JSON Schema for validation
│   ├── api/                    # FastAPI backend
│   ├── web/                    # HITL frontend (HTML/CSS/JS)
│   ├── db/                     # PostgreSQL schemas & queries
│   │   └── schema.sql          # Audit table + KPI views
│   ├── scripts/                # Remediation shell scripts
│   └── tests/                  # Unit & integration tests
├── infra/                      # Infrastructure setup (Zabbix templates, triggers)
├── experiment/                 # Experiment execution & data
│   ├── scenarios/              # Fault injection scripts
│   ├── verify/                 # Health verifiers (define end-of-round)
│   ├── baseline/               # Manual remediation data
│   ├── hitl/                   # HITL workflow data
│   └── analysis/               # Results analysis scripts
├── docker-compose.yml
├── requirements.txt
├── CHANGELOG.md
├── .env.example
└── README.md
```

---

## 📊 KPIs (Experiment Evaluation)

The system is validated through controlled experiments comparing manual remediation (baseline) vs. HITL workflow across 3 failure scenarios:

| KPI | Metric | Target |
|:----|:-------|:-------|
| **MTTR Reduction** | `(MTTR_baseline - MTTR_hitl) / MTTR_baseline × 100%` | 50% – 90% reduction |
| **Manual Steps** | Number of operator interventions per incident | Reduced to **1 click** |
| **Heuristic Accuracy** | `Successful remediations / Total attempts × 100%` | **> 80%** |

### Failure Scenarios

1. **Disk Space Saturation** — Filesystem exceeds 95% usage
2. **Anomalous CPU Consumption** — Sustained CPU usage above 90%
3. **Critical Service Interruption** — Essential service stopped/crashed

---

## 🎓 Academic Context

This project is developed as an undergraduate thesis (**Trabalho de Graduação**) in **Systems Analysis and Development (ADS)** at **Fatec**.

It contributes to the fields of **AIOps (AI for IT Operations)**, **Expert Systems**, and **Explainable AI**, demonstrating that lightweight symbolic approaches can deliver significant operational improvements without the complexity and opacity of ML-based solutions.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Caio Franson da Silva**

---

*Built with ☕ and determination.*
