#!/usr/bin/env sh
# probe-worktree.sh <repo_root> — worktree capability oracle for /develop:init.
# Echoes a status word to stdout and exits 0 (usage error: 3); a one-line reason goes to stderr
# on the non-ok paths. POSIX sh; no bashisms; NO git-version parsing (the live add/remove IS the
# test). The temp worktree lives in SYSTEM temp (mktemp -d), NEVER under the repo's .claude/, and
# a trap cleans it up on ANY exit so an interrupt cannot leak a registered worktree or temp dir.
#
# Status contract (stated ONCE, here):
#   ok          — repo can create + remove a worktree; /develop:run is good to go.
#   no-commits  — repo has no commits yet; worktrees become available after the first commit.
#   blocked     — add failed (old git, bare/shallow/exotic repo); surfaces at the Phase 5 gate.
set -f
root=$1
if [ -z "$root" ]; then
  echo "usage: probe-worktree.sh <repo_root>" >&2
  exit 3
fi

# zero-commit guard FIRST — never run the add, never hard-stop.
if ! git -C "$root" rev-parse --verify HEAD >/dev/null 2>&1; then
  echo "worktrees become available after the first commit" >&2
  echo no-commits
  exit 0
fi

tmp=$(mktemp -d 2>/dev/null) || { echo "cannot create a temp dir for the probe" >&2; echo blocked; exit 0; }
wt="$tmp/probe"

cleanup() {
  git -C "$root" worktree remove --force "$wt" >/dev/null 2>&1
  rm -rf "$tmp"
}
trap cleanup EXIT INT TERM   # installed BEFORE the add, so a partial add cannot leak

if git -C "$root" worktree add --detach "$wt" >/dev/null 2>&1; then
  echo ok
  exit 0
fi
echo "git worktree add failed (old git, or a bare/shallow/exotic repo)" >&2
echo blocked
exit 0
