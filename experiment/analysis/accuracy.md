# Human-assessed HITL accuracy

Validated locally on 2026-10-06 with synthetic rounds in disposable PostgreSQL 16.15. All seven
migrations applied; the database view, Python calculation and API response agreed, including
rounding and failures without incidents. Deployment on the laboratory server remains unvalidated.
No research results have been collected.

## Definition

One attempt is one HITL round with `descartada=false` and an explicit human assessment in
`resolvido`. Successes are attempts with `resolvido=true`. Accuracy is `100 * successes / attempts`,
rounded to one decimal place, half up. Results are grouped by the injected scenario.

Valid failed rounds count in the denominator, including false negatives without an incident,
wrong operational rules and rejected recommendations. Unassessed, discarded and baseline rounds
are excluded. An empty sample produces no scenario result, rather than a fabricated percentage.
The assessment must follow the protocol: measured sustained recovery, correct diagnosis, the
rule's timeout and collateral review. An executor exit code alone cannot establish accuracy.

## CSV snapshot

From the repository root, using the existing database configuration and Python environment:

```bash
python -m experiment.analysis.accuracy --output experiment/analysis/accuracy.csv
```

The exporter reads `experiment_run` directly; it does not require an audit link or modify evidence.
It validates classification before creating a file and refuses to replace an existing snapshot.
CSV columns: `cenario`, `tentativas`, `sucessos`, `taxa_acerto_pct`. Preserve the raw round export
and database evidence alongside each accuracy snapshot. This is an aggregate snapshot, not a new
source of individual classifications or an inferential statistical test.

## Database view and API

Migration `007_acerto_avaliacao_humana` replaces `vw_kpi03_acerto` with the same definition, without
altering primary rows or earlier migrations. Its columns are the four CSV fields above. The old
`regra_disparada` grouping/column is removed; actual operational rules remain in `audit_log`.
`GET /api/v1/kpis` exposes the new shape under `kpi03_acerto` after the migration is applied.
The API serializes the decimal percentage as a JSON string (for example, `"66.7"`).
Update consumers that expected the old grouping.

With Docker Engine running, rebuild the API to include the new migration before applying it:

```bash
docker compose up -d --build polaris-api
docker compose exec -T polaris-api python -m src.db.migrate
docker compose exec -T polaris-api python -m src.db.migrate --status
```

The migration runs transactionally through the existing migration runner. The regression tests cover Python aggregation and real PostgreSQL/API equivalence with synthetic
rounds. They passed locally; database tests remain skipped when PostgreSQL is unavailable. Use
only a disposable test database: the integration fixtures truncate volatile tables.
Do not interpret the old unmigrated view as the corrected accuracy calculation.
