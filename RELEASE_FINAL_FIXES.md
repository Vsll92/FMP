# Release Final Fixes

This package includes the final trust/QA fixes applied after the Goal Distribution fix.

## Fixed / hardened
- H2H metric helpers now normalize short aliases internally (`Lens`, `PSG`, `Monaco`, `Marseille`, etc.).
- Pre/post report goal-distribution validation is headless and reproducible; report-team title cannot remain Lens when another team is selected.
- Smoke-test PDF export uses a compact shared report model so CI remains reproducible.
- `export_model_pdf()` now safely renders string or dict tactical findings/player notes and works with compact report models.
- Release QA was made fast and headless while still checking the visible trust blockers: aliases, Lens–Marseille score truth, Wyscout coverage, player positions, radar max normalization, position-specific influence, valid touch counts, H2H Last Meeting, selected-team goal profile, xG caveats, documentation, and PDF export.
- Pitch-map legacy/H2H helper layers were moved closer to the same valid-event semantics used by Touch Map.
- Goal/Profile report caveats now explicitly explain Wyscout official xG vs Estimated event xG.

## Verified in this environment
- `python -m compileall .` passes.
- `python scripts/run_release_readiness_checks.py` reports `RELEASE-READY` with 20/20 checks.
- `python tests/test_goal_distribution.py` reports 16/16 selected-team goal-distribution checks.
- `python scripts/run_smoke_tests.py` printed 20/20 critical smoke tests passed; on this sandbox the Python process can remain alive after printing due dependency/runtime thread cleanup, so the release gate is the authoritative fast headless check.

## Honest caveat
Full visual PDF chart/map embedding depends on Kaleido/Chrome or Playwright in the local environment. Without that dependency, the PDF exporter produces a non-empty table/logo/model-based fallback and warns in release QA.
