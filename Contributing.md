# Contributing to ForgetTrace

Thanks for taking a look. This started as a focused, solo project, so the contribution
process is intentionally lightweight for now.

## Getting set up

```bash
git clone https://github.com/THISHA-SAMPATH/forgettrace.git
cd forgettrace
pip install -e .
pip install pytest
pytest tests/ -v
```

You'll also need a running DataHub instance to test against real lineage data — see
the Setup section in [README.md](README.md).

## Where the interesting problems are

If you want to dig in, these are the areas with the most room to grow:

- **Staleness detection** (`traversal.py`) — currently a fixed time-threshold. A better
  model would account for how frequently a given pipeline actually runs, rather than
  using one constant for every platform.
- **Confidence scoring** (`traversal.py`) — the decay function is simple and linear
  right now. There's room for a more principled model that factors in edge type,
  not just hop count.
- **Batch processing** — right now `forgettrace trace` handles one subject at a time.
  Supporting a list of identifiers in one run is a natural next step.

## Code style

- Type hints throughout, Python 3.11+ syntax (`str | None`, not `Optional[str]`)
- Keep functions focused — most of the existing modules are under 150 lines by design
- Add a test for any new logic in `traversal.py`, `audit.py`, or `remediation.py` —
  these are the modules where a silent bug would be the most costly (an incomplete
  erasure trace is a compliance problem, not just a code smell)

## Reporting issues

Open a GitHub issue with a clear description of what you expected vs. what happened.
If it's a bug in lineage traversal, include the DataHub data pack you were testing
against (e.g. `showcase-ecommerce`) so it's reproducible.

## License

By contributing, you agree that your contributions will be licensed under the
Apache License 2.0, the same license as the rest of the project.
