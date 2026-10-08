# Descriptive experiment report

`python -m experiment.analysis.report` produces raw rounds, descriptive CSV tables, a Markdown
report and optional standalone PNG/PDF figures. It reads a CSV snapshot or the configured PostgreSQL
database using one read-only repeatable-read transaction. It never assesses rounds, approves
remediation, modifies database evidence or replaces an existing report directory.

## Environment and commands

Calculations and `--no-graphs` need only the project's existing requirements. Plotting uses the
optional, pinned Matplotlib requirement inside `experiment/analysis/requirements.txt`. Keep a
separate environment for publication analysis; plotting packages are not API/engine dependencies.
From the repository root, in Bash:

```bash
python -m venv experiment/analysis/.venv
source experiment/analysis/.venv/bin/activate
python -m pip install -r requirements.txt -r experiment/analysis/requirements.txt
python -m experiment.analysis.report --input experiment/analysis/rounds.csv --output experiment/analysis/report_01 --kind collected
```

On Fish, activate `experiment/analysis/.venv/bin/activate.fish`; on Windows PowerShell,
`experiment\analysis\.venv\Scripts\Activate.ps1`. Use `python3` for venv creation on Unix when
`python` is unavailable. Input/output paths resolve relative to the repository, independently of
the invoking working directory. Use a new output directory for each snapshot.

Omit `--input` to read the database configured by the existing environment. The database connection
must be dedicated and idle. Add `--no-graphs` to export tables without Matplotlib. CLI errors return
2 and avoid printing DSNs or credentials. The database regression fixtures require a disposable
PostgreSQL database: they truncate volatile tables.

Always pass `--kind synthetic` for test fixtures. Synthetic reports and figures carry prominent
labels, and all CSV tables contain `tipo_dados`. A snapshot labeled synthetic cannot be relabeled
collected. A collected label records the operator's choice; it does not certify the laboratory or
prove correctness. No synthetic preview is a research result.

## Outputs

- `rodadas.csv`: all rounds, including failures, unassessed/discarded rounds and literal commands;
  timestamps normalized to UTC, MTTR recomputed from t0/t5, optional linked audit timestamps/count.
- `resumo.csv`: counts/exclusions and mean, sample standard deviation, minimum and maximum of
  MTTR and manual steps for every scenario/arm present.
- `comparacao.csv`: per-arm sample counts/means/reductions and an additional comparison restricted
  to matching repetition numbers in the same scenario; unmatched measurements remain explicit.
- `acerto.csv`: human-assessed HITL accuracy per scenario and pooled successes/attempts.
- `decomposicao.csv`: mean phase durations and total from the same complete chronological HITL subset.
- `resultados.md`: tables, eligibility definitions, gaps and the source snapshot SHA-256.
- `manifest.json`: data kind, round count, snapshot hash and hashes of every report artifact.
- Optional `mttr`, `passos`, `acerto`, `decomposicao` figures, each in 300 dpi PNG and vector PDF.
  A figure is omitted when its eligible sample is empty. Empty reports show `[A COLETAR]`, not zeros.

Malformed input is rejected before output creation. If rendering fails, only the new report directory
is removed; existing evidence remains untouched. Tables retain numerical precision; Markdown rounds
for display. Figures report n, and duration/effort error bars represent sample standard deviation.

## Eligibility and interpretation

MTTR is `ts_verificado_ok - ts_injecao` in seconds for assessed, non-discarded rounds with a measured
recovery. A failed correctness assessment can still have a measured MTTR; it stays in the summary.
Attempts without t5 are counted as missing, without imputing zero, timeout or successful recovery.
Manual steps use the recorded nonnegative count in assessed, non-discarded rounds, including failures.
An absent count is not an assumed HITL click. Sample standard deviation uses n−1; n<2 yields no deviation.

Reduction is `100 * (baseline_mean - hitl_mean) / baseline_mean`. A missing arm or zero baseline
produces no percentage. Negative reduction represents increased duration/effort. Unpaired summaries
use all eligible measurements with both counts visible; paired summaries use only equal scenario and
repetition identifiers. There is no significance test, confidence interval or population inference.

Accuracy follows `resolvido` for assessed, non-discarded HITL rounds, including failures without an
incident. It is rounded to one decimal, half up, matching the corrected accuracy view. The aggregate
uses pooled counts, not an average of scenario percentages. Human assessment remains responsible
for expected rule, sustained recovery within rule timeout and collateral review.

Reports reject duplicate IDs/non-discarded repetitions and mixing versions/SHA/KB, target or operator
among assessed, non-discarded rounds. Preserve the original snapshots; use separate derived cohort
files/databases if necessary, without editing primary records to force inclusion.

Decomposition requires exactly one linked audit record and six timezone-aware ordered timestamps:
t0→t1 detection, t1→t2 ingestion, t2→t3 processing/presentation, t3→t4 human decision, t4→t5
execution/recovery. Processing/presentation does not isolate inference time. Missing/ambiguous or
non-monotonic timelines are counted, not converted to negative or zero phases. There is no inferred
baseline decomposition. Phase totals use the same subset as all five segments.

This report queries primary rows directly. It does not use the earlier MTTR/steps/decomposition
views: those views have broader eligibility, and the original decomposition ends its last phase at
operational `ts_conclusao` instead of independent t5. Do not substitute those view results for these
report tables without reconciling the definitions. Accuracy view 007 is separately documented in
[accuracy.md](accuracy.md).
