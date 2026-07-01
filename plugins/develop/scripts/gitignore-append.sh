#!/usr/bin/env sh
# gitignore-append.sh <repo_root> <pattern> — idempotently ensure <pattern> is git-ignored.
# Echoes: added | already-present. Exit 0 (usage error: 3). POSIX sh; no bashisms.
# Covered if EITHER an exact-line match OR a parent-dir ignore already exists (e.g. a `.claude/`
# line already covers `.claude/worktrees/`), so re-runs never add a spurious duplicate line.
set -f
root=$1
pat=$2
if [ -z "$root" ] || [ -z "$pat" ]; then
  echo "usage: gitignore-append.sh <repo_root> <pattern>" >&2
  exit 3
fi
gi="$root/.gitignore"

if [ -f "$gi" ]; then
  if grep -Fxq "$pat" "$gi"; then echo already-present; exit 0; fi
  # walk parent dirs of the pattern: ".claude/worktrees/" -> ".claude/worktrees" -> ".claude"
  probe=${pat%/}
  while [ -n "$probe" ]; do
    parent=${probe%/*}
    [ "$parent" = "$probe" ] && parent=""     # no slash remained
    [ -n "$parent" ] || break
    if grep -Fxq "$parent/" "$gi" || grep -Fxq "$parent" "$gi"; then
      echo already-present; exit 0
    fi
    probe=$parent
  done
fi

# ensure a trailing newline before appending (printf, never echo -e)
if [ -f "$gi" ] && [ -s "$gi" ]; then
  last=$(tail -c 1 "$gi" 2>/dev/null)
  if [ -n "$last" ]; then printf '\n' >> "$gi"; fi
fi
printf '%s\n' "$pat" >> "$gi"
echo added
exit 0
