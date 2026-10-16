#!/usr/bin/env python3
"""Compare scenario results with the control using Fisher's exact test (standard library only). DRAFT.

Usage:
  python3 compare_scenarios.py docs/eval_scenarios.log
      reads the JSON block that eval_scenarios.py prints at the end of the log and compares every scenario with
      the control 'baseline-no-context', action by action.
  python3 compare_scenarios.py --counts k1 n1 k2 n2
      one quick two-sided test: k1 of n1 runs in group A versus k2 of n2 runs in group B.

How to read the p-values: with 20 runs per scenario only large differences are detectable. This is a table of
12 exploratory comparisons, so treat p < 0.01 as 'clear', 0.01-0.05 as 'suggestive', and anything above as 'no
evidence of a difference'. Report the counts, not only the p-values.
"""
import json
import re
import sys
from math import comb

ACTIONS = ("HALT", "RETRY_NAVIGATION", "REVERSE_AND_REPLAN")
CONTROL = "baseline-no-context"


def fisher_two_sided(k1, n1, k2, n2):
    total_k, total_n = k1 + k2, n1 + n2

    def prob(x):
        return comb(n1, x) * comb(n2, total_k - x) / comb(total_n, total_k)

    lo, hi = max(0, total_k - n2), min(n1, total_k)
    p_obs = prob(k1)
    return min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs * (1 + 1e-9)))


def label(p):
    return "clear" if p < 0.01 else "suggestive" if p < 0.05 else "no evidence"


def load_results(path):
    text = open(path, encoding="utf-8", errors="ignore").read()
    starts = [m.start() + 1 for m in re.finditer(r'\n\{\n  "', text)]
    if not starts:
        raise SystemExit("no JSON block found in the log (was the run complete?)")
    obj, _ = json.JSONDecoder().raw_decode(text[starts[-1]:])
    return obj


def main(argv):
    if len(argv) == 6 and argv[1] == "--counts":
        k1, n1, k2, n2 = map(int, argv[2:])
        p = fisher_two_sided(k1, n1, k2, n2)
        print(f"{k1}/{n1} vs {k2}/{n2}: p = {p:.4f} ({label(p)})")
        return 0
    if len(argv) != 2:
        print(__doc__)
        return 1
    res = load_results(argv[1])
    if CONTROL not in res:
        raise SystemExit(f"control scenario '{CONTROL}' not in the log")
    c = res[CONTROL]
    print(f"control '{CONTROL}': n={c['runs']}, decisions={c['decisions']}")
    print("\n| scenario | action | control | scenario | p | reading |")
    print("|---|---|---|---|---|---|")
    for name, r in res.items():
        if name == CONTROL:
            continue
        for a in ACTIONS:
            k1, k2 = c["decisions"].get(a, 0), r["decisions"].get(a, 0)
            p = fisher_two_sided(k1, c["runs"], k2, r["runs"])
            print(f"| {name} | {a} | {k1}/{c['runs']} | {k2}/{r['runs']} | {p:.4f} | {label(p)} |")
    timeouts = {n: r["decisions"].get("TIMEOUT", 0) for n, r in res.items() if r["decisions"].get("TIMEOUT")}
    if timeouts:
        print("\nWARNING: timeouts present:", timeouts)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
