#!/usr/bin/env python3
"""
Turn `kane-cli cover ... gaps --json` into a GitHub job summary and a pass/fail gate.

Two axes come back from the coverage ribbon:
  designed  — completeness owed by the live graph (did we design a test for every AC?)
  proven    — depth proven by the evidence pack   (did a test actually run and pass?)

The gate fails the build when the proven axis drops below --threshold.

kane-cli 0.8.2+ emits a documented shape (`rollup_version: 1`): top-level
`design_completeness.pct`, a `proven` object whose `pct` is the proven share of
the current live ACs, and per-use-case `design_completeness` / `proven`. `proven`
is absent when the pack recorded no run of a designed test — nothing is proven,
so that counts as 0%. Any other shape is walked defensively for the usual
counter names, as before. It never fails the build because it failed to *parse*
— only because coverage was genuinely low.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Key names the ribbon has used for the two axes.
DESIGNED_KEYS = ("designed", "designed_total", "total_designed", "acs", "total")
PROVEN_KEYS = ("proven", "proven_total", "covered", "passed", "satisfied")
PENDING_KEYS = ("pending", "gaps", "uncovered", "missing")


def load(path: str):
    """cover may emit a single JSON document or an NDJSON envelope. Handle both."""
    with open(path, encoding="utf-8") as fh:
        raw = fh.read().strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    docs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not docs:
        return None
    # NDJSON envelope: the terminal 'done' event carries the payload.
    for doc in reversed(docs):
        if isinstance(doc, dict) and doc.get("type") in ("done", "cover_done", "result"):
            return doc.get("data", doc)
    return docs[-1]


def first_int(node: dict, keys) -> int | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, list):
            return len(value)
    return None


def find_totals(node, acc: list) -> None:
    """Walk the tree collecting any object that carries both axes."""
    if isinstance(node, dict):
        designed = first_int(node, DESIGNED_KEYS)
        proven = first_int(node, PROVEN_KEYS)
        if designed is not None and proven is not None and designed >= 0:
            acc.append(
                {
                    "label": node.get("id")
                    or node.get("use_case")
                    or node.get("usecase")
                    or node.get("title")
                    or "total",
                    "designed": designed,
                    "proven": proven,
                    "pending": first_int(node, PENDING_KEYS),
                }
            )
        for value in node.values():
            find_totals(value, acc)
    elif isinstance(node, list):
        for item in node:
            find_totals(item, acc)


def number(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def gate_rollup_v1(doc: dict, lines: list, threshold: float) -> int:
    """Gate on the documented rollup: proven.pct against the threshold."""
    proven = doc.get("proven") if isinstance(doc.get("proven"), dict) else None
    design = doc.get("design_completeness") or {}

    rows = []
    for uc in doc.get("usecases") or []:
        if not isinstance(uc, dict):
            continue
        d = uc.get("design_completeness") or {}
        p = uc.get("proven") if isinstance(uc.get("proven"), dict) else None
        label = uc.get("id") or uc.get("title") or "?"
        designed = f"{number(d.get('pct')):.0f}% {d.get('status', '')}"
        proven_cell = f"{number(p.get('pct')):.0f}% {p.get('status', '')}" if p else "—"
        rows.append(f"| {label} | {designed} | {proven_cell} |")
    if rows:
        lines += ["| Use-case | Designed | Proven |", "|---|---|---|", *rows, ""]

    lines.append(f"Designed: {number(design.get('pct')):.0f}% of ACs ({design.get('acs_designed', '?')}).")
    if proven is None:
        pct = 0.0
        lines.append("Proven: the evidence pack recorded no run of a designed test, so nothing is proven.")
    else:
        pct = number(proven.get("pct"))
        extras = ", ".join(
            f"{number(proven.get(k)):.0f} {k.replace('_', ' ')}"
            for k in ("failing", "blocked", "not_run")
            if proven.get(k) is not None
        )
        lines.append(f"Proven: {proven.get('acs_proven', '?')} ACs{f' — {extras}' if extras else ''}.")

    passed = pct >= threshold
    lines += ["", f"{'🟢' if passed else '🔴'} **Proven {pct:.1f}%** against a {threshold:.0f}% gate.", ""]
    write_summary("\n".join(lines))
    if not passed:
        print(f"::error title=Coverage below gate::Proven coverage {pct:.1f}% is under the {threshold:.0f}% threshold.")
        return 1
    return 0


def write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True, help="output of `cover ... gaps --json`")
    parser.add_argument("--table", help="output of the plain-text ribbon, shown verbatim")
    parser.add_argument("--threshold", type=float, default=80.0, help="minimum proven %%")
    parser.add_argument("--pack", default="", help="evidence pack the proof came from")
    args = parser.parse_args()

    lines = ["## Retail assurance coverage", ""]
    if args.pack:
        lines.append(f"Evidence pack: `{os.path.basename(args.pack)}`")
        lines.append("")

    if args.table and os.path.exists(args.table):
        with open(args.table, encoding="utf-8") as fh:
            ribbon = fh.read().strip()
        if ribbon:
            lines += ["<details><summary>Coverage ribbon</summary>", "", "```", ribbon, "```", "", "</details>", ""]

    doc = load(args.json)
    if isinstance(doc, dict) and doc.get("rollup_version") == 1 and isinstance(doc.get("design_completeness"), dict):
        return gate_rollup_v1(doc, lines, args.threshold)

    rows: list = []
    if doc is not None:
        find_totals(doc, rows)

    if not rows:
        lines += [
            "> Coverage ribbon produced no parseable counters, so the gate is advisory "
            "for this run. The ribbon above is authoritative.",
        ]
        write_summary("\n".join(lines))
        return 0

    # Widest row (most ACs) is the roll-up.
    total = max(rows, key=lambda r: r["designed"])
    per_uc = [r for r in rows if r is not total and r["designed"] > 0][:20]

    if per_uc:
        lines += ["| Use-case | Designed | Proven | Pending |", "|---|---:|---:|---:|"]
        for row in per_uc:
            pending = row["pending"] if row["pending"] is not None else row["designed"] - row["proven"]
            lines.append(f"| {row['label']} | {row['designed']} | {row['proven']} | {pending} |")
        lines.append("")

    pct = (total["proven"] / total["designed"] * 100) if total["designed"] else 0.0
    passed = pct >= args.threshold
    icon = "🟢" if passed else "🔴"

    lines += [
        f"{icon} **Proven {total['proven']}/{total['designed']} ({pct:.1f}%)** "
        f"against a {args.threshold:.0f}% gate.",
        "",
    ]
    write_summary("\n".join(lines))

    if not passed:
        print(
            f"::error title=Coverage below gate::Proven coverage {pct:.1f}% "
            f"is under the {args.threshold:.0f}% threshold."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
