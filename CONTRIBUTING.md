# Contributing

1. Create a branch for each change.
2. Run the core QA commands before submitting changes:

```bash
python -m compileall .
python scripts/run_smoke_tests.py
python scripts/run_release_readiness_checks.py
```

3. Add or update tests for any metric, callback, report, or map logic change.
4. Update `docs/KPI_DEFINITIONS.md` if you change a metric formula.
5. Update `docs/METHODOLOGY.md` if you change source hierarchy, model logic, or report interpretation.
6. Keep Wyscout official metrics separate from estimated/event-derived metrics.
