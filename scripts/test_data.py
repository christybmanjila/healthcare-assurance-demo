#!/usr/bin/env python3
"""
Test data for the designed healthcare-website suite.

`kane-cli testrun` has no --variables flag; members read variables from
.testmuai/variables/*.json. That directory is gitignored, so on a runner it is empty
unless this script fills it.

Unlike the retail demo, this site has no login/registration flow, so there is nothing
secret and nothing that needs a per-run-unique value — provisioning is just
test-data/healthcare.json plus start_url from the environment.

  provision   write test-data/healthcare.json + start_url to .testmuai/variables/ci.json
  check       fail before any browser starts if a member uses a {{variable}} that
              nothing supplies — those tests cannot pass on any re-run

Variable names in test-data/healthcare.json are a best-effort guess at what kane-cli
will actually design tests around — reconcile them against the real *_test.md files
after the first `design tests` run (see README "Test data").
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

DATA_FILE = Path("test-data/healthcare.json")
OUT_FILE = Path(".testmuai/variables/ci.json")
VARIABLE_DIRS = (Path.home() / ".testmuai/kaneai/variables", Path(".testmuai/variables"))

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\.[^}]*)?\s*\}\}")


def provision() -> int:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    variables = {k: v for k, v in data.items() if not k.startswith("_")}

    if os.environ.get("APP_URL"):
        variables["start_url"] = {"value": os.environ["APP_URL"]}

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(variables, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(variables)} variables to {OUT_FILE}: {', '.join(sorted(variables))}")
    return 0


def supplied_keys() -> set[str]:
    keys: set[str] = set()
    for directory in VARIABLE_DIRS:
        for path in sorted(glob.glob(str(directory / "*.json"))):
            try:
                keys.update(k for k in json.loads(Path(path).read_text(encoding="utf-8")) if not k.startswith("_"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"::warning::Could not read {path}: {exc}")
    return keys


def frontmatter_keys(text: str) -> set[str]:
    """Keys under a root `variables:` block in the test's own frontmatter."""
    match = re.match(r"---\n(.*?)\n---", text, re.S)
    if not match:
        return set()
    keys, inside = set(), False
    for line in match.group(1).splitlines():
        if re.match(r"variables:\s*$", line):
            inside = True
        elif inside and (m := re.match(r"  ([A-Za-z_][A-Za-z0-9_]*):", line)):
            keys.add(m.group(1))
        elif inside and line and not line.startswith(" "):
            inside = False
    return keys


def stored_in_run(text: str) -> set[str]:
    """Names the test itself captures ("store X as name") — resolved at run time."""
    return set(re.findall(r"\bas\s+['\"`]?([A-Za-z_][A-Za-z0-9_]*)", text))


def check(members_file: str) -> int:
    members = [line.strip() for line in Path(members_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    supplied = supplied_keys()
    missing: dict[str, list[str]] = defaultdict(list)

    for member in members:
        text = Path(member).read_text(encoding="utf-8")
        known = supplied | frontmatter_keys(text) | stored_in_run(text)
        for name in sorted(set(PLACEHOLDER.findall(text)) - known):
            missing[name].append(member)

    if not missing:
        print(f"Test data OK: every variable used by {len(members)} member(s) is supplied.")
        return 0

    for name, tests in sorted(missing.items()):
        print(f"::error title=Missing test data::{{{{{name}}}}} is used by {len(tests)} test(s) "
              f"but nothing supplies it — add \"{name}\" to {DATA_FILE}.")
        for test in tests:
            print(f"    {test}")
    print(f"{len(missing)} variable(s) unsupplied; stopping before any browser minute is spent.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("provision")
    check_parser = sub.add_parser("check")
    check_parser.add_argument("members", help="file listing one *_test.md path per line")
    args = parser.parse_args()
    return provision() if args.command == "provision" else check(args.members)


if __name__ == "__main__":
    sys.exit(main())
