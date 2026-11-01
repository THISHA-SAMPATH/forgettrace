# ForgetTrace — An Agent for Provable Data Erasure

## Motivation

"Right to be forgotten" requests (GDPR Article 17, and equivalents like India's DPDP
Act) sound simple until you actually have to fulfill one. Deleting a customer's row in
the source database is the easy 10%. The hard 90% is everything derived from that row —
a Spark job that copied it into an enriched table, a dashboard built on top of that, an
ML feature store that trained on it six months ago. Miss any of those, and the deletion
isn't actually complete. Worse, there's usually no record proving what _was_ checked,
which is its own compliance risk when a regulator asks for evidence.

This is a narrow, opinionated take on solving that: an agent that doesn't just find
where sensitive data lives, but proves it — with a tamper-evident, auditable trail a legal or
privacy team could actually use.

## What ForgetTrace does

Give it a subject identifier (`patient_id: P10432`). It:

1. Searches DataHub metadata for candidate datasets whose schemas may contain that identifier column
2. Requires an authorised subject-data connector to confirm the specific identifier value before treating a candidate as a direct match
3. Walks the **downstream lineage graph** recursively from each confirmed match — every derived
   table, dashboard, and ML feature — using DataHub's MCP Server
4. Scores each finding with a **numeric confidence score** — 1.0 for a direct match,
   decaying with hop count and halved further if the lineage edge is stale/unconfirmed —
   so it's clear at a glance which findings are certain and which need a second look
5. Flags anything DataHub can't confirm confidently: stale lineage edges, missing
   timestamps, edges near the traversal depth limit — so a human reviews the risky parts
   instead of the agent silently trusting incomplete metadata
6. Generates a **remediation task queue** from those flags — concrete next steps
   (owner, priority, action) rather than just a report to read
7. Produces a **tamper-evident report hash** (SHA-256 over its own contents) — a way to detect changes when the trusted original hash is protected. This is not a digital signature or proof of author identity. The report records exactly
   what was found, when, so it can be handed to a legal/compliance team or a regulator,
   and any later tampering with the report is detectable

This is deliberately narrow: one clean, complete workflow rather than a broad toolkit.
See [`examples/sample_report.json`](examples/sample_report.json) for real output.

## PostgreSQL subject verification connector

ForgetTrace includes an optional PostgreSQL connector for checking whether a
specific subject value exists in an explicitly configured table. It does not
automatically scan every database table: each DataHub dataset URN must be mapped
to a schema/table, and each searchable subject column must be allow-listed.

Install the optional driver in the project environment:

```powershell
python -m pip install -e ".[postgres,dev]"
```

Keep database credentials out of source control. In PowerShell, set a connection
string for the current terminal session (use a dedicated database role with
`SELECT` permission only on the tables ForgetTrace is allowed to inspect):

```powershell
$env:FORGETTRACE_POSTGRES_DSN = "postgresql://forgettrace_reader:YOUR_PASSWORD@localhost:5432/demo"
```

Example connector setup using synthetic data names:

```python
import os

from forgettrace.postgres_connector import PostgresDataset, PostgresSubjectChecker

checker = PostgresSubjectChecker(
    dsn=os.environ["FORGETTRACE_POSTGRES_DSN"],
    datasets={
        "urn:li:dataset:(urn:li:dataPlatform:postgres,public.customers,PROD)":
            PostgresDataset(
                schema="public",
                table="customers",
                subject_columns=frozenset({"customer_id"}),
            )
    },
)

# In an async workflow: found = await checker.contains_subject(
#     "urn:li:dataset:(urn:li:dataPlatform:postgres,public.customers,PROD)",
#     "customer_id",
#     "DEMO-100",
# )
```

The connector uses parameterised values and safely quoted identifiers. It returns
a boolean and does not log the subject value. The connector is currently a
separate building block; the CLI workflow still needs configuration and wiring
to pass it into `find_direct_matches`.

## Important implementation boundary

DataHub metadata search identifies candidate datasets; it does not inspect table rows
and cannot prove that a specific subject value exists. The core now fails closed unless
an authorised `SubjectDataChecker` is supplied. A production database connector and
its access-control policy are required before subject-level matches can be confirmed.

The current project traces metadata lineage and generates review tasks. It does not
execute data deletion or independently verify erasure. Do not describe a request as
completed or erased based only on a lineage report.

## Why the audit trail matters more than the search

Most "find the customer's data" tools stop at a list of table names. A compliance team
doesn't need a list — it needs _evidence_: what was checked, what's confirmed vs.
uncertain, and a protected integrity record so the report's contents can be checked later. That's
the part of this project that took the most work, and the part that's meant to actually
be useful to a data/privacy team, not just a demo.

## Architecture

```
subject ID
   │
   ▼
[DataHub MCP Server] ── search ──▶ direct-match datasets
   │
   ▼
[traversal.py] ── recursive BFS downstream, cycle-safe, hop-limited
   │              flags stale/unverifiable edges, scores each node's confidence
   ▼
[remediation.py] ── turns flags + low-confidence nodes into an owned task queue
   │
   ▼
[audit.py] ── builds structured report + SHA-256 integrity hash
   │
   ▼
JSON report with an integrity hash (+ CLI table + task list)
```

- **`forgettrace/datahub_client.py`** — thin wrapper over the official
  [DataHub MCP Server](https://github.com/acryldata/mcp-server-datahub), spawned over
  stdio, exposing `search`, `get_entities`, `get_lineage`
- **`forgettrace/traversal.py`** — the downstream walk: visited-set cycle/diamond
  handling, hop limits, staleness flagging, per-node confidence scoring
- **`forgettrace/remediation.py`** — converts flagged issues and low-confidence nodes
  into a deduplicated, prioritized task queue
- **`forgettrace/audit.py`** — report construction + SHA-256 signing/verification
- **`forgettrace/cli.py`** — `forgettrace trace` and `forgettrace verify` commands

## Setup

Requires a running DataHub instance (see
[DataHub Quickstart](https://docs.datahub.com/docs/quickstart)) and Python 3.11+.

```bash
# 1. Spin up DataHub and load a sample dataset with real lineage
datahub docker quickstart
datahub datapack load showcase-ecommerce --force

# 2. Install ForgetTrace
git clone https://github.com/THISHA-SAMPATH/forgettrace.git
cd forgettrace
pip install -e .

# 3. Point at your DataHub instance
export DATAHUB_GMS_URL="http://localhost:8080"
export DATAHUB_GMS_TOKEN=""

# 4. Run a trace
forgettrace trace --subject-column customer_id --subject-value <a-customer-id>

# 5. Verify a report hasn't been tampered with
forgettrace verify reports/<request-id>.json
```

## Testing

20 unit tests cover the parts most likely to break silently: cycle-safe graph
traversal, confidence-score decay, staleness penalties, and SHA-256 tamper detection
on the audit report.

```bash
pip install pytest
pytest tests/ -v
```

## Sample data used

Demo runs against DataHub's `showcase-ecommerce` sample data pack (~1,000 entities
across Snowflake, S3, dbt, Looker, Tableau, and PowerBI, with real lineage) — safe for
an Apache 2.0 public repo.

## Status / limitations

Built solo as a focused, end-to-end project rather than a broad platform. Known
limitations, noted honestly rather than glossed over:

- Staleness detection is a simple time-threshold heuristic, not a full data-quality model
- Traversal depth is capped (configurable via `--max-hops`) — extremely deep lineage
  graphs will flag for manual review rather than traverse indefinitely
- Tested against DataHub's sample data packs; not yet run against a production-scale
  (100k+ entity) graph

## Future work

- Batch mode: process a list of subject identifiers in one run
- Pluggable staleness model (replace the fixed time threshold with something that
  accounts for how frequently a given pipeline actually runs)
- Optional integration with a ticketing system (Jira, Linear) to push remediation
  tasks directly instead of leaving them in the JSON report

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
