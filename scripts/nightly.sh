#!/usr/bin/env bash
# The nightly job: scrape every live source into the raw store, build from scratch, publish.
# Runs anywhere bash and git do (Git Bash on Windows, Linux, macOS); scripts/install-nightly.sh
# schedules it.
#
# It runs in a worktree of its own, so it never touches a working tree anyone edits: fetch,
# check out origin/<branch>, then `python -m pipeline nightly` (new committed history into the raw
# store, scrape, build, snapshot, deal table).
#
#   --branch B    the code to run (default main)
#   --push        commit the snapshot and the deal table and push them to main, which deploys the
#                 site; if main moved meanwhile, build again on it from the raws and retry
#   --build-only  build from the pages the raw store already holds, no scraping: with --push, the
#                 way to put a code change on the site at once
#   (neither)     push nothing; log how this build's snapshot differs from main's
#
# Each run's log: $CAR_RESEARCH_RAW/logs/nightly/<date>.log
set -euo pipefail

branch=main push=0 build_only=0
repo="${CAR_RESEARCH_REPO:-$HOME/car-research}"
worktree="${CAR_RESEARCH_WORKTREE:-$HOME/car-research-nightly}"
while [ $# -gt 0 ]; do
  case "$1" in
    --branch) branch="$2"; shift 2 ;;
    --push) push=1; shift ;;
    --build-only) build_only=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

: "${CAR_RESEARCH_RAW:?CAR_RESEARCH_RAW is not set: it names the raw store folder}"
export PYTHONUTF8=1 PYTHONUNBUFFERED=1
# Poppler's pdftotext reads Hyundai's PDF guides (the parser is written against its layout):
# CAR_RESEARCH_PDFTOTEXT, else one installed under ~/tools, else whatever is on the PATH.
if [ -z "${CAR_RESEARCH_PDFTOTEXT:-}" ]; then
  found=$(find "$HOME/tools" -path '*poppler*' \( -name pdftotext -o -name pdftotext.exe \) 2>/dev/null | head -n 1 || true)
  [ -n "$found" ] && export CAR_RESEARCH_PDFTOTEXT="$found"
fi
if command -v uv >/dev/null 2>&1; then py=(uv run --quiet --python 3.12 python)
elif [ -x "$HOME/.local/bin/uv" ] || [ -x "$HOME/.local/bin/uv.exe" ]; then py=("$HOME/.local/bin/uv" run --quiet --python 3.12 python)
else py=(python3); fi

day=$(date -u +%Y-%m-%d)
log_dir="$CAR_RESEARCH_RAW/logs/nightly"
mkdir -p "$log_dir"
exec >> "$log_dir/$day.log" 2>&1
trap 'echo "nightly: FAILED at line $LINENO ($(date -u +%FT%TZ))"' ERR

echo "nightly: $(date -u +%FT%TZ), branch $branch, push $push, build-only $build_only"
[ -d "$worktree" ] || git -C "$repo" worktree add --detach "$worktree"
cd "$worktree"
git fetch -q origin
git checkout -q --detach --force "origin/$branch"
export CAR_RESEARCH_DB="$worktree/data/car-research.sqlite"

if [ "$build_only" = 1 ]; then
  "${py[@]}" -m pipeline build --deal-table docs/deal-comparison.md
else
  "${py[@]}" -m pipeline nightly
  "${py[@]}" -m pipeline raw-status
fi

if [ "$push" = 0 ]; then
  echo "compared with main's snapshot (new = this build, old = main):"
  "${py[@]}" scripts/compare_snapshots.py web/public/data git:origin/main
  echo "nightly: done $(date -u +%FT%TZ)"
  exit 0
fi

message="data: nightly build $day"
[ "$build_only" = 1 ] && message="data: build from the raw store $day"
for attempt in 1 2 3; do
  git add -- web/public/data docs/deal-comparison.md
  if git diff --cached --quiet; then echo "nothing changed"; break; fi
  git -c user.name="car-research nightly" -c user.email="nightly@car-research.local" commit -q -m "$message"
  if git push -q origin HEAD:main; then echo "pushed"; break; fi
  [ "$attempt" = 3 ] && { echo "main kept moving; this snapshot was not pushed"; exit 1; }
  # main moved while we worked: take it as it now is and build again from the raws (no new fetching).
  echo "main moved; building again on it (attempt $attempt)"
  git fetch -q origin
  git checkout -q --detach --force origin/main
  "${py[@]}" -m pipeline build --deal-table docs/deal-comparison.md
done
echo "nightly: done $(date -u +%FT%TZ)"
