#!/usr/bin/env python3
"""Fast headless smoke-test runner for Football Analytics Pro.

Runs the release-readiness gate only. The gate includes the critical visible bug
checks: team aliases, Wyscout score truth, radar max-normalization, position-
specific influence, valid Touch Map counts, H2H Last Meeting scope, and the
pre-match Goal Distribution regression (it must follow the selected opponent).

Run the dedicated regression suite separately when needed:
    python tests/test_goal_distribution.py
"""
from __future__ import annotations
import os, sys, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

LF = "France_League_1_25-26"
start = time.time()
try:
    from components.release_qa import run_release_readiness_checks
    qa = run_release_readiness_checks(LF)
    passed = sum(1 for c in qa.get("checks", []) if c.get("ok"))
    total = len(qa.get("checks", []))
    ok = bool(qa.get("pass"))
    print("\n" + "=" * 72)
    print(f"SMOKE RESULT: {'PASS' if ok else 'FAIL'} ({passed}/{total} checks) in {time.time()-start:.1f}s")
    print("=" * 72, flush=True)
    sys.exit(0 if ok else 1)
except Exception as e:
    print(f"SMOKE RESULT: FAIL :: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
