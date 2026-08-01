# ForgetTrace — An Agent for Provable Data Erasure

Built for [Build with DataHub: The Agent Hackathon](https://datahub.devpost.com/) — *Agents That Do Real Work* track.

## The problem

When a "right to be forgotten" (GDPR/DPDP) request comes in, finding the customer's row
in the source database is the easy part. The hard part — the part that turns into a
compliance incident — is everything derived from that row: the Spark job that copied it
into an enriched table, the dashboard built on top of that, the ML feature store that
trained on it six months ago. If any of those get missed, the deletion isn't actually
complete, and there's no record proving what *was* checked.

## What ForgetTrace does

Give it a subject identifier (`patient_id: P10432`). It:

1. Searches DataHub for every dataset that directly contains that identifier
2. Walks the **downstream lineage graph** recursively from each match — every derived
   table, dashboard, and ML feature — using DataHub's MCP Server
3. Scores each finding with a **numeric confidence score** — 1.0 for a direct match,
   decaying with hop count and halved further if the lineage edge is stale/unconfirmed —
   so it's clear at a glance which findings are certain and which need a second look
4. Flags anything DataHub can't confirm confidently: stale lineage edges, missing
   timestamps, edges near the traversal depth limit — so a human reviews the risky parts
   instead of the agent silently trusting incomplete metadata
5. Generates a **remediation task queue** from those flags — concrete next steps
   (owner, priority, action) rather than just a report to read
6. Produces a **signed audit report** (SHA-256 over its own contents) — proof of exactly
   what was found, when, so it can be handed to a legal/compliance team or a regulator,
   and any later tampering with the report is detectable

This is deliberately narrow: one clean, complete workflow rather than a broad toolkit.
See [`examples/sample_report.json`](examples/sample_report.json) for real output.

## Why the audit trail matters more than the search

Most "find the customer's data" tools stop at a list of table names. A compliance team
doesn't need a list — it needs *evidence*: what was checked, what's confirmed vs.
uncertain, and a signature so the record can't be quietly edited after the fact. That's
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
[audit.py] ── builds structured report, SHA-256 signs it
   │
   ▼
signed JSON report (+ CLI table + task list)
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
datahub datapack load healthcare

# 2. Install ForgetTrace
git clone <this-repo>
cd forgettrace
pip install -e .

# 3. Point at your DataHub instance
export DATAHUB_GMS_URL="http://localhost:8080"
export DATAHUB_GMS_TOKEN="<your-token>"

# 4. Run a trace
forgettrace trace --subject-column patient_id --subject-value P10432

# 5. Verify a report hasn't been tampered with
forgettrace verify reports/<request-id>.json
```

## Sample data used

Demo runs against DataHub's `healthcare` sample datapack (synthetic patient records,
~55k rows, with planted data quality issues) — safe for an Apache 2.0 public submission.

## Status / limitations

Built solo in a two-week hackathon window. Known limitations, noted honestly rather than
glossed over:
- Staleness detection is a simple time-threshold heuristic, not a full data-quality model
- Traversal depth is capped (configurable via `--max-hops`) — extremely deep lineage
  graphs will flag for manual review rather than traverse indefinitely
- Tested against DataHub's sample datapacks; not yet run against a production-scale
  (100k+ entity) graph

## License

Apache License 2.0 — see [LICENSE](LICENSE).
