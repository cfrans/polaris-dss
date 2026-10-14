# Editable diagrams

Every image has a same-named Mermaid `.mmd` source, `.svg` and high-resolution `.png` export.
Sources describe the implementation reviewed on 2026-10-14, not a planned future architecture.

| Diagram | Purpose |
|:--|:--|
| [Architecture](architecture.png) / [source](architecture.mmd) | Deployment, telemetry, approval and separate instrumentation |
| [Components](components.png) / [source](components.mmd) | Application modules and dependencies |
| [Instrumented HITL sequence](hitl_sequence.png) / [source](hitl_sequence.mmd) | Committed approval before execution; parallel independent observer |
| [Data model overview](data_model_overview.png) / [source](data_model_overview.mmd) | Core physical entities and foreign keys |
| [Full data model](data_model.png) / [source](data_model.mmd) | All six tables/columns; large reference image |
| [Derived views](derived_views.png) / [source](derived_views.mmd) | Four KPI views, with logical rather than foreign-key dependencies |

The overview intentionally selects fields. Use [the physical schema catalog](../data_model.md)
for exact SQL types and constraints. The database allows multiple incident links to a round;
the experiment CLI enforces its stricter single-link contract. Supporting tables without a
physical foreign key are shown separately; diagram proximity does not imply a constraint.

Exports used Mermaid CLI 11.17.0, Mermaid 11.17.2 and a locally installed Chrome browser.
Rendering is a documentation toolchain, not a frontend dependency or runtime build step.
With that CLI available, an equivalent command is:

```bash
mmdc -i docs/diagrams/architecture.mmd -o docs/diagrams/architecture.png -b white -s 2
```

Configure the renderer's existing browser as required by the local environment. No external
diagram service or laboratory records are needed to render these sources.
