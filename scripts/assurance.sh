#!/usr/bin/env bash
#
# Assurance stage: requirements -> context graph -> committed use-cases -> designed tests.
#
# The assurance commands are conversational by design. In CI there is nobody to
# answer, so every call passes `--mode ci`, which is the "never ask me anything"
# policy. Two exit codes matter here and they are NOT the usual ones:
#
#   0  done
#   3  paused and resumable  (the agent had a question it could not assume past)
#   2  refused before doing work — usage error, a design gate (e.g. an unreviewed
#      use-case), or auth/infra. setup-kane has already proved the credentials,
#      so the refusal message in the log is the thing to read.
#
# Exit 3 is not a crash. The session id is preserved under .context/sessions/ and
# a human resumes it locally with:
#   kane-cli context extract --resume <sid> --message "..."
#   kane-cli design tests    --resume <sid> --message "..."
#
set -euo pipefail

REQ_GLOB="${REQ_GLOB:-requirements/*.md}"
MAX_PAIRS="${MAX_PAIRS:-12}"
AUTO_APPROVE="${AUTO_APPROVE:-true}"
FORCE_DESIGN="${FORCE_DESIGN:-false}"

step() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }

# Runs one assurance command, annotates its outcome, and returns its exit code.
# It never exits the script (an `exit` here used to end the whole run from inside
# a loop): each stage decides what a non-zero code means for it. Call it as
# `run_assurance ... || code=$?` so `set -e` does not fire on a paused/failed run.
#
# When RUN_LOG names a file (the design loop sets it), the command's output is
# also copied there so the caller can read kane-cli's own verdict.
RUN_LOG=""

run_assurance() {
  local label="$1"; shift
  local code=0
  if [ -n "$RUN_LOG" ]; then
    # tee keeps the live log; PIPESTATUS keeps the command's exit code, not tee's.
    "$@" 2>&1 | tee "$RUN_LOG" || code=${PIPESTATUS[0]}
  else
    "$@" || code=$?
  fi
  case "$code" in
    0) ;;
    3)
      echo "::warning title=Assurance paused::${label} paused with an open question."
      echo "PAUSED_STAGE=${label}" >> "${GITHUB_ENV:-/dev/null}"
      kane-cli context sessions || true
      ;;
    2)
      if [ -n "$RUN_LOG" ] && design_gate_refused "$RUN_LOG"; then
        :  # already designed — not an error; the design loop reports it
      else
        echo "::error title=Assurance refused::${label} exited 2 — a usage error, a design gate, or auth/infra. The refusal and its next step are in the log above."
      fi
      ;;
    *)
      echo "::error title=Assurance failed::${label} exited ${code}."
      ;;
  esac
  return "$code"
}

# kane-cli's design gate answers before any model call (free): a use-case with a
# design record — for this version of it or an earlier one — is refused, exit 2:
#   design: 'uc-1' is already designed @ v1 — current; use --force to redesign
#   design: 'uc-1' was designed @ v1 — the use-case is now @ v2 (STALE); use --force to redesign
# The record can exist while `cover gaps` still rates the use-case undesigned
# (criteria saved, no tests yet), so only the gate itself can say.
design_gate_refused() {
  grep -Eq "^design: '[^']+' (is already designed|was designed) @ .*use --force to redesign" "$1"
}

# A designed test lives twice: as a node in the graph and as a *_test.md file whose
# frontmatter carries `assurance: id: t-N`. kane-cli cannot rebuild a missing file
# from the graph ("restore the deleted file"), and only .context/ used to be cached,
# so every file designed in CI was lost after its run. Designed files are now kept
# in STATE_DIR — cached together with .context/ — and put back while their test is
# still live in the graph.
STATE_DIR=".kane-state/tests"

# Live test ids in the graph, one per line.
graph_test_ids() {
  kane-cli context list --json 2>/dev/null | jq -r 'select(.label == "test") | .id' 2>/dev/null || true
}

# The `assurance: id:` of every *_test.md under the given files/directories, one per line.
test_ids_in() {
  find "$@" -name '*_test.md' -exec awk '
      FNR == 1 { fm = 0; blk = "" }
      { sub(/\r$/, "") }
      /^---[[:space:]]*$/ { fm++; next }
      fm == 1 && /^[^[:space:]]/ { blk = $1 }
      fm == 1 && blk == "assurance:" && $1 == "id:" { print $2 }
    ' {} + 2>/dev/null || true
}

restore_designed_tests() {
  if [ ! -d "$STATE_DIR" ]; then
    echo "No designed test files kept from an earlier run."
    return 0
  fi
  local live on_disk f id restored=0
  live=" $(graph_test_ids | tr '\n' ' ') "
  on_disk=" $(test_ids_in .testmuai/tests | tr '\n' ' ') "
  mkdir -p .testmuai/tests
  for f in "$STATE_DIR"/*_test.md; do
    [ -e "$f" ] || continue
    id=$(test_ids_in "$f" | head -n 1)
    # Only a test that is still live (not superseded or retired since), that the
    # checkout does not already have — a committed file always wins — and never
    # over an existing file of the same name.
    if [ -z "$id" ] || [[ "$live" != *" ${id} "* ]] || [[ "$on_disk" == *" ${id} "* ]] \
       || [ -e ".testmuai/tests/$(basename "$f")" ]; then
      continue
    fi
    cp "$f" .testmuai/tests/
    restored=$((restored + 1))
  done
  echo "Restored ${restored} designed test file(s) kept from an earlier run."
}

stash_designed_tests() {
  local f
  rm -rf "$STATE_DIR"
  mkdir -p "$STATE_DIR"
  for f in .testmuai/tests/*_test.md; do
    [ -e "$f" ] || continue
    if [ -n "$(test_ids_in "$f")" ]; then
      cp "$f" "$STATE_DIR/"
    fi
  done
  echo "Kept $(find "$STATE_DIR" -name '*_test.md' | wc -l | tr -d ' ') designed test file(s) for the next run."
}

# ---------------------------------------------------------------------------
step "0/5  Restore designed test files kept from earlier runs"
restore_designed_tests

# ---------------------------------------------------------------------------
step "1/5  Ingest requirement sources into the context graph"
# --mode ci lands the sources without pulling us into the extract chat.
# shellcheck disable=SC2086
kane-cli context ingest $REQ_GLOB --mode ci

# ---------------------------------------------------------------------------
step "2/5  Extract use-cases from the ingested sources"
EXTRACT_CODE=0
run_assurance "context extract" kane-cli context extract --mode ci || EXTRACT_CODE=$?
# Paused is fine — what was committed before the question is still designable.
# Anything else stops here: without use-cases there is nothing to design.
if [ "$EXTRACT_CODE" -ne 0 ] && [ "$EXTRACT_CODE" -ne 3 ]; then
  exit "$EXTRACT_CODE"
fi

# ---------------------------------------------------------------------------
step "3/5  Approve derived use-cases (the human gate)"
# `context list --json` emits one JSON object per line: {id,cid,label,title,trust,fresh}
mapfile -t INFERRED < <(kane-cli context list --type usecase --inferred --json 2>/dev/null | jq -r '.id' || true)

if [ "${#INFERRED[@]}" -gt 0 ] && [ "$AUTO_APPROVE" = "true" ]; then
  echo "Approving ${#INFERRED[@]} derived use-case(s): ${INFERRED[*]}"
  kane-cli context review --approve "${INFERRED[@]}" --mode agent
elif [ "${#INFERRED[@]}" -gt 0 ]; then
  echo "::notice::${#INFERRED[@]} use-case(s) awaiting review. Run 'kane-cli context review' locally and commit .context/."
else
  echo "Nothing new in the review queue."
fi

mapfile -t USECASES < <(kane-cli context list --type usecase --json 2>/dev/null | jq -r '.id' || true)
if [ "${#USECASES[@]}" -eq 0 ]; then
  echo "::error title=No use-cases::Extraction produced nothing to design against."
  exit 1
fi
echo "Live use-cases: ${USECASES[*]}"
printf '%s\n' "${USECASES[@]}" > usecases.txt

# ---------------------------------------------------------------------------
step "4/5  Design acceptance criteria, scenarios and 1:1 tests per use-case"
DESIGN_ARGS=(--mode ci --max "$MAX_PAIRS")
[ "$FORCE_DESIGN" = "true" ] && DESIGN_ARGS+=(--force)

# Which use-cases already have a design. `cover gaps` reads only the local graph
# (no model call) and rates each one undesigned | partial | complete. Designing a
# partial or complete use-case again is a redesign: in ci mode the agent either
# reworks the suite or decides nothing is missing, commits nothing and exits 1 —
# on every run, paid each time. So only undesigned use-cases are designed here;
# force_design redesigns all of them, and the gaps of a partial design stay
# visible in the coverage ribbon. An unknown or missing status is designed, as
# before, and a missing status table is reported rather than hidden.
declare -A DESIGN_STATUS=() STALE_ACS=()
if [ "$FORCE_DESIGN" != "true" ]; then
  while IFS=$'\t' read -r id status stale; do
    if [ -n "$id" ]; then
      DESIGN_STATUS["$id"]="$status"
      STALE_ACS["$id"]="$stale"
    fi
  done < <(kane-cli cover gaps --stage design --json 2>/dev/null \
    | jq -r '.usecases[]? | [.id, (.design_completeness.status // ""), ((.stale_acs // 0) | tostring)] | @tsv' 2>/dev/null \
    || true)
  if [ "${#DESIGN_STATUS[@]}" -eq 0 ]; then
    echo "::warning title=Design status unavailable::'kane-cli cover gaps --stage design --json' returned no per-use-case status; every use-case will be designed."
  fi
fi

SKIPPED=(); PAUSED=(); FAILED=()
for uc in "${USECASES[@]}"; do
  status="${DESIGN_STATUS[$uc]:-}"
  if [ "$status" = "partial" ] || [ "$status" = "complete" ]; then
    echo "Skipping ${uc}: it already has a ${status} design (run with force_design to redesign)."
    stale="${STALE_ACS[$uc]:-0}"
    if [[ "$stale" =~ ^[0-9]+$ ]] && [ "$stale" -gt 0 ]; then
      echo "::notice title=Stale design (${uc})::${stale} acceptance criteria changed with the requirements. Reconcile locally with 'kane-cli maintain reconcile', then commit .context/."
    fi
    SKIPPED+=("$uc")
    continue
  fi
  step "    designing ${uc}"
  code=0
  RUN_LOG=$(mktemp)
  run_assurance "design tests (${uc})" \
    kane-cli design tests --use-case "$uc" "${DESIGN_ARGS[@]}" || code=$?
  if [ "$code" -eq 2 ] && design_gate_refused "$RUN_LOG"; then
    echo "Skipping ${uc}: kane-cli reports it is already designed (run with force_design to redesign)."
    if grep -q '(STALE)' "$RUN_LOG"; then
      echo "::notice title=Stale design (${uc})::The use-case changed after it was designed. Refresh it locally with 'kane-cli maintain evolve ${uc}', then commit .context/."
    fi
    SKIPPED+=("$uc")
    rm -f "$RUN_LOG"; RUN_LOG=""
    continue
  fi
  rm -f "$RUN_LOG"; RUN_LOG=""
  case "$code" in
    0) ;;
    3) PAUSED+=("$uc") ;;
    *) FAILED+=("$uc") ;;
  esac
done
echo "Design: $(( ${#USECASES[@]} - ${#SKIPPED[@]} - ${#PAUSED[@]} - ${#FAILED[@]} )) designed," \
     "${#SKIPPED[@]} already designed, ${#PAUSED[@]} paused, ${#FAILED[@]} failed."

# ---------------------------------------------------------------------------
step "5/5  Verify the commit chain and report what was produced"
# fsck proves the graph is internally consistent — the audit story for the buyer.
kane-cli context fsck || echo "::warning::context fsck reported drift; see the log."

# Say so when a live test has no file, instead of quietly running a smaller suite.
mapfile -t GRAPH_TESTS < <(graph_test_ids)
ON_DISK=" $(test_ids_in .testmuai/tests | tr '\n' ' ') "
MISSING=()
for t in "${GRAPH_TESTS[@]}"; do
  [[ "$ON_DISK" == *" ${t} "* ]] || MISSING+=("$t")
done
if [ "${#MISSING[@]}" -gt 0 ]; then
  echo "::warning title=Designed tests not on disk::${#MISSING[@]} test(s) in the graph have no *_test.md and will not run: ${MISSING[*]}. Their files were never kept (designed before test files were cached, or the cache was evicted): commit them from the assurance-graph artifact of the run that designed them, or redesign with force_design."
fi

stash_designed_tests

# `|| true`: with pipefail a missing tests dir would otherwise abort here, before
# the outputs and the "No tests designed" error below.
TEST_COUNT=$( { find .testmuai/tests -name '*_test.md' 2>/dev/null || true; } | wc -l | tr -d ' ')
echo "Designed test files on disk: ${TEST_COUNT}"

if [ -n "${GITHUB_OUTPUT:-}" ]; then
  {
    echo "usecase_count=${#USECASES[@]}"
    echo "test_count=${TEST_COUNT}"
  } >> "$GITHUB_OUTPUT"
fi

if [ "$TEST_COUNT" -eq 0 ]; then
  echo "::error title=No tests designed::Design produced no *_test.md files."
  exit 1
fi

# Every use-case has had its turn and the outputs above are written; a design
# failure still fails the stage, as it always has.
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "::error title=Design failed::${#FAILED[@]} use-case(s) failed to design: ${FAILED[*]}."
  exit 1
fi
