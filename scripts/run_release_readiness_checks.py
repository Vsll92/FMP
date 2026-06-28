#!/usr/bin/env python3
"""
Reproducible release-readiness runner.

Usage (from the ligue1_dashboard/ directory):
    python scripts/run_release_readiness_checks.py
    python scripts/run_release_readiness_checks.py --league France_League_1_25-26

Exit code 0 = release-ready (all strict checks pass), 1 = blocked.
Prints per-check PASS/FAIL, timing for the run, warnings (e.g. skipped optional
checks), and a clear list of release blockers. Strict mode is on by default:
a text-only PDF, a stale report, a leaking H2H filter, or a pitch footer that
disagrees with the dots will FAIL the gate, not pass silently.
"""
import argparse
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _discover_default_league():
    from data_loader import discover_leagues
    leagues = discover_leagues()
    if not leagues:
        print("No leagues discovered under data/.", file=sys.stderr)
        sys.exit(2)
    # Prefer the main Ligue 1 league for the default release gate. Cup/knockout
    # competitions can be checked explicitly with --league France_Coupe_de_France_25-26.
    for lg in leagues:
        folder = lg["folder"] if isinstance(lg, dict) else lg
        display = lg.get("display_name", "") if isinstance(lg, dict) else ""
        if "League_1" in folder or "Ligue" in display:
            return folder
    return leagues[0]["folder"] if isinstance(leagues[0], dict) else leagues[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default=None, help="League folder (default: first discovered)")
    args = ap.parse_args()

    league = args.league or _discover_default_league()
    print("=" * 72)
    print(f"RELEASE READINESS — league: {league}")
    print("=" * 72)

    from components.release_qa import run_release_readiness_checks
    t0 = time.time()
    r = run_release_readiness_checks(league)
    elapsed = time.time() - t0

    checks = r["checks"]
    passed = sum(1 for c in checks if c["ok"])
    failed = [c for c in checks if not c["ok"]]
    gates = [c for c in checks if "GATE" in c["name"]]

    for c in checks:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['name']}"
              + (f"  ::  {str(c.get('detail',''))[:88]}" if c.get("detail") else ""))

    print("-" * 72)
    for w in r.get("warnings", []):
        print(f"  [WARN/SKIP] {w}")

    print("=" * 72)
    print(f"RESULT: {'RELEASE-READY' if r['pass'] else 'BLOCKED'}  "
          f"({passed}/{len(checks)} checks, {len(gates)} visible-bug gates) "
          f"in {elapsed:.1f}s")
    if failed:
        print("\nRELEASE BLOCKERS:")
        for c in failed:
            print(f"  ✗ {c['name']}  — {str(c.get('detail',''))[:100]}")
    print("=" * 72)
    return 0 if r["pass"] else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)
