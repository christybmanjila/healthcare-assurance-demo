#!/usr/bin/env python3
"""
Test data for the designed healthcare-website suite.

`kane-cli testrun` has no --variables flag; members read variables from
.testmuai/variables/*.json. That directory is gitignored, so on a runner it is empty
unless this script fills it.

Unlike the retail demo, this site has no login/registration flow, so nothing here is a
real secret. But it does need one piece of real server-side setup: the
"already booked by another patient" scenario (other_patient_booked_slot_time) can only be
true if something actually books that slot before the browser suite starts — a browser
session's own cookie can't be pre-seeded from outside it, so that fixture is a real HTTP
call, not just a JSON value. See PRESEED_DOCTOR_ID / PRESEED_OTHER_PATIENT_SLOT below.

A few other variables (patient_with_booked_appointments, patient_with_cancelable_appointment,
self_booked_slot_time) hit the same limitation — a fresh browser session starts with an empty
cart, and only actions taken *within that same session* can populate it. For those,
test-data/healthcare.json supplies natural-language instructions (not just a bare value)
telling the agent to perform the booking itself as part of the scenario. This is the
correct mechanism for kane-cli's design (tests are executed by an LLM-driven agent reading
natural language, not by literal string substitution into a fixed script), but it's the
least certain part of this file — watch the first few real runs and adjust the wording if
the agent doesn't reliably act on it.

  provision   write test-data/healthcare.json + start_url + real pre-booked fixture to
              .testmuai/variables/ci.json
  check       fail before any browser starts if a member uses a {{variable}} that
              nothing supplies — those tests cannot pass on any re-run

Variable names were reconciled against the actual designed *_test.md files (run #2 of the
workflow) — see the commit that added this reconciliation for the full list of what each
test expected.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

DATA_FILE = Path("test-data/healthcare.json")
OUT_FILE = Path(".testmuai/variables/ci.json")
VARIABLE_DIRS = (Path.home() / ".testmuai/kaneai/variables", Path(".testmuai/variables"))

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)(?:\.[^}]*)?\s*\}\}")

# Must match test-data/healthcare.json's "other_patient_booked_slot_time" value and the
# doctor referenced by doctor_name/doctor_profile_url/open_slot_time/self_booked_slot_time
# there — all three fixture slots below belong to the same doctor (Dr. Nia Osei / "osei")
# so the "reject an already-booked slot" test can exercise all three states (open,
# self-booked, other-patient-booked) on one doctor without any of them colliding.
PRESEED_DOCTOR_ID = "osei"
# Both slots pre-booked before the suite starts. The app makes no distinction between
# "this patient" and "another patient" bookings (a taken slot rejects anyone), so both
# the self-booked and other-patient-booked fixtures need is a slot that's genuinely
# already taken — there's no reason to route one of them through an in-session agent
# instruction when a real HTTP call is exactly as correct and has none of the
# interpretation risk (see the run-4 failure record for reject-booking-an-already-booked:
# the agent never actually carried out the embedded "book this yourself first" text).
PRESEED_SELF_BOOKED_SLOT = "2026-09-22 10:00"
PRESEED_OTHER_PATIENT_SLOT = "2026-09-23 13:00"


def _book(app_url: str, slot: str, label: str) -> None:
    body = urllib.parse.urlencode({
        "doctor_id": PRESEED_DOCTOR_ID,
        "appointment_type": "Follow-up",
        "slot": slot,
    }).encode()
    req = urllib.request.Request(f"{app_url}/book", data=body, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        print(f"Pre-seeded: {PRESEED_DOCTOR_ID} / {slot} booked as '{label}' before the suite starts.")
    except urllib.error.URLError as exc:
        print(f"::warning::Could not pre-seed {label} booking: {exc}")


def preseed_bookings() -> None:
    """Book PRESEED_SELF_BOOKED_SLOT and PRESEED_OTHER_PATIENT_SLOT server-side, before
    the browser suite starts, so both are genuinely already-taken when the
    "reject an already-booked slot" test runs — a real HTTP call is the only way to
    establish this; nothing that runs inside kane-cli's own browser session later could
    reach back and pre-seed itself."""
    app_url = os.environ.get("APP_URL")
    if not app_url:
        print("::warning::APP_URL not set; skipping booking pre-seed.")
        return
    _book(app_url, PRESEED_SELF_BOOKED_SLOT, "this patient")
    _book(app_url, PRESEED_OTHER_PATIENT_SLOT, "another patient")


def provision() -> int:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    variables = {k: v for k, v in data.items() if not k.startswith("_")}

    if os.environ.get("APP_URL"):
        variables["start_url"] = {"value": os.environ["APP_URL"]}

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(variables, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(variables)} variables to {OUT_FILE}: {', '.join(sorted(variables))}")

    preseed_bookings()
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
    """Names the test itself establishes as it runs via explicit "store X as name" /
    "note ... as name" phrasing.

    A `baseline_*`-prefixed placeholder used to get a free pass here on the theory that
    kane-cli's own "capture baseline: ..." phrasing resolves it at runtime. It doesn't:
    run 4's failure record for the per-page test showed the literal string
    "{{baseline_tile_count}}" left unresolved and handed to the agent verbatim, stuck with
    nothing to compare against. Every {{placeholder}}, baseline_* included, needs a real
    supplied value — see test-data/healthcare.json."""
    return set(re.findall(r"\b(?:as|note)\s+['\"`]?([A-Za-z_][A-Za-z0-9_]*)", text))


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
