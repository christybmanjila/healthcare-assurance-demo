# Healthcare Website · Agentic Assurance & Evidence in GitHub Actions

A GitHub Actions pipeline that takes a **healthcare website requirements document** and ends
with a **sealed evidence pack** and a **requirement-level coverage gate** — every stage
driven by `kane-cli`, nothing hand-authored.

Modeled directly on
[jayakumar331/retail-assurance-demo](https://github.com/jayakumar331/retail-assurance-demo).
The retail demo points at an already-public sandbox storefront
(`ecommerce-playground.lambdatest.io`); there's no public healthcare equivalent, so this repo
bundles its own sample site (`website/`) and starts it in-job instead.

App under test: `website/server.py`, started at `http://localhost:5050` in the evidence job.

---

## The story in one line

Most QA pipelines can tell you *tests passed*. This one tells you **which requirements are
proven, by which run, with the screenshots to back it**.

```
requirements/healthcare-website.md
        │  kane-cli context ingest + extract
        ▼
   context graph  (use-cases, reviewed, commit-chained)
        │  kane-cli design tests
        ▼
   designed *_test.md  (ACs → scenarios → 1:1 tests)
        │  kane-cli testrun run
        ▼
   ONE sealed .evidence pack  ──  kane-cli evidence validate --profile L1
        │  kane-cli cover gaps
        ▼
   designed × proven ribbon  →  PR comment + build gate
```

## The sample website

`website/server.py` is a small, self-contained Flask app — no LLM, no external calls, no
database — standing in for a real patient-facing site: **Riverbend Clinic**. It implements
doctor search, specialty browsing, doctor profiles, and appointment booking with a shared
in-memory calendar (so double-booking is a real, testable condition). Everything in
`requirements/healthcare-website.md` was verified by hand against this app before being
committed — see that file's acceptance criteria for the exact behavior kane-cli will design
tests against.

Run it yourself:

```bash
cd website && pip install -r requirements.txt
PORT=5050 python server.py
open http://localhost:5050
```

**When you have a real website to test**, point `APP_URL` at it, delete `website/`, drop the
"Start the sample website" / "Stop the sample website" steps from the workflow's `evidence`
job, and rewrite `requirements/healthcare-website.md` for the real site — see "Adapting it to
a named account" below.

## What's in the repo

| Path | What it does |
|---|---|
| `website/` | The sample healthcare site under test |
| `requirements/healthcare-website.md` | The single source of truth. Five requirement areas with acceptance criteria, matched to `website/server.py` exactly. Edit this and the graph re-opens. |
| `.github/workflows/healthcare-assurance-evidence.yml` | The three-stage pipeline. |
| `.github/actions/setup-kane/action.yml` | Installs kane-cli, does non-interactive auth, points at the runner's Chrome. |
| `scripts/assurance.sh` | Ingest → extract → review → design, with correct handling of exit code 3. |
| `scripts/coverage_gate.py` | Turns the coverage ribbon into a job summary and a pass/fail gate. |
| `scripts/test_data.py`, `test-data/healthcare.json` | Supplies the tests' `{{variables}}` on the runner and refuses to run a suite that is missing any. |

## Setup

Add four repository secrets (Settings → Secrets and variables → Actions):

| Secret | Where to get it |
|---|---|
| `LT_USERNAME` | TestMu AI / LambdaTest profile |
| `LT_ACCESS_KEY` | TestMu AI / LambdaTest access key |
| `TESTMUAI_PROJECT_ID` | `kane-cli projects list` |
| `TESTMUAI_FOLDER_ID` | `kane-cli folders list` |

Unlike the retail demo, there's no login/registration flow on this sample site, so no
shopper-account secrets are needed. If you swap in a real site that has one, add its
credentials as secrets the same way and read them in `scripts/test_data.py`.

Then push, open a PR against `requirements/` or `website/`, or run it manually from the
Actions tab.

### Test data

Designed tests carry `{{variables}}` for data the requirements never pinned. `testrun` reads
them from `.testmuai/variables/*.json`, which is gitignored, so the evidence job builds
`.testmuai/variables/ci.json` with `scripts/test_data.py provision` from
`test-data/healthcare.json` plus `start_url` from `APP_URL`.

The variable names in `test-data/healthcare.json` are a **best-effort guess** at what
kane-cli will actually design tests around (there's no shopper-account precedent to copy
from the way the retail demo had) — reconcile them against the real `*_test.md` files after
the first `design tests` run: look for `{{...}}` placeholders the check step flags as
missing, and add matching keys to the JSON file.

Preflight runs `scripts/test_data.py check`: if any member uses a variable nothing supplies,
the job stops with the variable name and the tests that need it, before a browser starts.

### A note on shared state

`website/server.py`'s appointment slots (3 per doctor, 10 doctors) are shared, in-memory,
and consumed for the life of the process — that's what makes double-booking testable at all.
It also means a suite that books more appointments than there are slots will start seeing
real "slot no longer available" results near the end of a run. Fine at the default
`MAX_PAIRS: 12`; worth widening `website/server.py`'s `DOCTORS` list if you raise it a lot.

## The three stages

### 1 · Assurance — requirements to designed tests

```bash
kane-cli context ingest requirements/*.md --mode ci
kane-cli context extract --mode ci
kane-cli context review --approve <ids> --mode agent
kane-cli design tests --use-case uc-... --mode ci --max 12
kane-cli context fsck
```

Three things worth pointing at during a demo:

- **`--mode ci` is the "never ask me" policy.** In a pipeline nobody can answer, so `ci`
  makes the agent assume documented defaults instead of hanging.
- **Exit code 3 is not a failure.** It means the agent paused on a question it could not
  assume past, and the session is resumable — `kane-cli context extract --resume <sid>
  --message "..."`. `scripts/assurance.sh` surfaces that as a GitHub warning with the session
  id rather than a red X.
- **The graph is cached between runs.** Unchanged requirements are not re-extracted and not
  re-billed. The designed `*_test.md` files travel with the graph (`.kane-state/`): kane-cli
  cannot rebuild a test file from the graph, so without them a designed test never runs.

For a governed setup, flip `AUTO_APPROVE` to `false`: derived use-cases stay in the review
queue, a human runs `kane-cli context review` locally, and `.context/` gets committed to the
repo.

### 2 · Evidence — one execution, one sealed pack

```bash
kane-cli testrun run .testmuai/tests/*_test.md --dry-run
kane-cli testrun run .testmuai/tests/*_test.md \
  --name "Healthcare regression #42" --parallel 2 --on-failure continue --headless
kane-cli evidence validate .testmuai/evidence/<id>.evidence --profile L1 --json
```

`testrun` runs M tests as **one execution** — one sealed pack for the whole suite. The
workflow starts `website/server.py` before this stage and stops it after, whatever the
outcome. The pack uploads with 90-day retention — that's the artifact you hand a prospect's
QA lead or drop into an audit.

To open a downloaded pack:

```bash
kane-cli evidence serve healthcare-regression-42.evidence
```

### 3 · Coverage — designed × proven

```bash
kane-cli cover --from <pack> gaps --rollup strict --json
```

Two axes: **completeness** owed by the live graph (did we design something for every AC?)
and **depth** proven by the pack (did a test actually run and pass?). The gate fails the
build below `COVERAGE_THRESHOLD` (default 80%) and posts the ribbon as a PR comment.

## Running it locally first

```bash
npm install -g @testmuai/kane-cli
kane-cli login --oauth
kane-cli config set-url http://localhost:5050

# in another terminal: cd website && PORT=5050 python server.py

kane-cli context ingest requirements/healthcare-website.md
kane-cli context list --type usecase
kane-cli design tests --use-case <uc-id>
kane-cli testrun run .testmuai/tests/*_test.md
kane-cli cover --from <pack> gaps
```

## Keeping it true as requirements change

```bash
kane-cli maintain reconcile      # every proposed change HOLDS as a review card
kane-cli maintain evolve <ref>   # re-design the affected use-case; untouched items preserved
```

## Adapting it to a named account

1. Replace `requirements/healthcare-website.md` with the prospect's own PRD, epic, or
   acceptance notes.
2. Point `APP_URL` at their real environment, delete `website/`, and drop the
   "Start the sample website" / "Stop the sample website" steps in the `evidence` job.
3. Add any real login/account secrets `scripts/test_data.py` needs to provision, following
   the pattern in the retail demo's `scripts/test_data.py` for a shopper account.
4. Set `COVERAGE_THRESHOLD` to whatever their release gate actually is.

## Note on flags

Command surface verified against `@testmuai/kane-cli@0.8.10`; the commands the
design-skip logic reads (`cover gaps --stage design --json`, `context list --json`) were
re-checked on `0.8.11`, per the retail demo this was copied from. CI installs the version
pinned in `.github/actions/setup-kane/action.yml` (`version` input, currently `0.8.11`);
bump it deliberately and run `kane-cli changelog` first.
