#!/usr/bin/env sh
# worktree-guard — a safe, STACK-AGNOSTIC PreToolUse(Bash) guard for the develop flow.
#
# Blocks two classes of git that can destroy a phase's or a sibling worktree's work:
#   1) Destructive working-tree git (checkout / switch / restore / clean / stash, and
#      reset --hard|--keep|--merge) — ALWAYS. The develop loop is read-only git except
#      add/commit/worktree, so these only ever wipe uncommitted or sibling-phase work.
#   2) Mutating git (commit / push / merge / rebase) while on the default branch
#      (main/master) or a detached HEAD — feature work belongs on a worktree branch.
#
# It knows nothing about any language/build tool — only git. Exit 0 = allow, 2 = block.
#
# Matching is anchored to command POSITION: each segment of a compound command (split on
# ; && || | &) is inspected, leading env assignments and git global flags (-C / --git-dir /
# --work-tree / -c) are consumed, and only a real `git <subcommand>` head matches — so
# `echo "git commit"` and `git log --grep="git push"` are NOT blocked, while
# `git -C /other/worktree reset --hard` (the sibling-worktree footgun) IS.

set -f   # no pathname expansion while we tokenise (a stray * must not glob)

# SELF-GATE: enforce only in develop-managed repos; fail-open (allow) otherwise. Resolve the
# MAIN checkout (mirrors run/SKILL.md step 2) so the marker is visible from the main checkout
# AND any worktree under it (a run executes inside a worktree whose .claude/ lacks the
# uncommitted develop.config.json). Inert outside develop repos — the one place this fact lives.
marker=""
gcd=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || gcd=""
if [ -n "$gcd" ]; then
  marker="${gcd%/}/../.claude/develop.config.json"
elif [ -n "$CLAUDE_PROJECT_DIR" ]; then
  marker="$CLAUDE_PROJECT_DIR/.claude/develop.config.json"
fi
[ -n "$marker" ] && [ -f "$marker" ] || exit 0   # not develop-managed -> allow all

input=$(cat)

# --- extract the command string: jq → python3 → sed → raw ---
cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
fi
if [ -z "$cmd" ] && command -v python3 >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | python3 -c 'import sys,json
try: print((json.load(sys.stdin).get("tool_input") or {}).get("command",""))
except Exception: pass' 2>/dev/null)
fi
if [ -z "$cmd" ]; then
  cmd=$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p' | head -n1)
fi
[ -z "$cmd" ] && exit 0

block() { echo "develop:worktree-guard — $1" >&2; exit 2; }

# Branch at a dir (arg1; empty = cwd). Echoes the branch, "DETACHED", or "" (unknown).
branch_at() {
  if [ -n "$1" ]; then b=$(git -C "$1" rev-parse --abbrev-ref HEAD 2>/dev/null) || { echo ""; return; }
  else b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || { echo ""; return; }; fi
  [ "$b" = "HEAD" ] && { echo "DETACHED"; return; }
  echo "$b"
}

# Inspect ONE command segment, passed as word tokens ($1, $2, ...).
inspect() {
  while [ $# -gt 0 ]; do            # drop leading env assignments (FOO=bar git ...)
    case "$1" in [A-Za-z_]*=*) shift ;; *) break ;; esac
  done
  [ $# -gt 0 ] && [ "$1" = "git" ] || return 0   # only a real git invocation at the head
  shift
  gitdir=""
  while [ $# -gt 0 ]; do            # consume git global flags, capturing a -C/--git-dir target
    case "$1" in
      -C) gitdir="$2"; shift; [ $# -gt 0 ] && shift ;;
      --git-dir=*) gitdir="${1#--git-dir=}"; shift ;;
      --git-dir) gitdir="$2"; shift; [ $# -gt 0 ] && shift ;;
      --work-tree=*) gitdir="${1#--work-tree=}"; shift ;;
      --work-tree) gitdir="$2"; shift; [ $# -gt 0 ] && shift ;;
      -c) shift; [ $# -gt 0 ] && shift ;;
      -*) shift ;;
      *) break ;;
    esac
  done
  [ $# -gt 0 ] || return 0
  sub="$1"; shift
  rest=" $* "

  # 1) destructive working-tree git — always blocked
  case "$sub" in
    checkout|switch|restore|clean|stash)
      block "refusing destructive 'git $sub' — it can discard uncommitted or sibling-worktree work. The develop loop is read-only git; run it yourself if you truly need it." ;;
    reset)
      case "$rest" in
        *" --hard "*|*" --keep "*|*" --merge "*)
          block "refusing 'git reset$rest'— it discards working-tree state." ;;
      esac ;;
  esac

  # 2) mutating git on the default branch / detached HEAD
  case "$sub" in
    commit|push|merge|rebase)
      case "$rest" in *" --abort "*|*" --continue "*|*" --skip "*|*" --quit "*) return 0 ;; esac
      b=$(branch_at "$gitdir")
      case "$b" in
        main|master|DETACHED)
          block "refusing 'git $sub' on '$b' — feature work belongs on a worktree branch (the develop loop creates one in step 2)." ;;
      esac ;;
  esac
  return 0
}

# Split into segments on shell separators (one per line), then inspect each. The segment
# list is captured by the for-loop before inspect() runs, so block()'s exit reaches the shell.
segs=$(printf '%s' "$cmd" | sed 's/&&/\n/g; s/||/\n/g; s/|/\n/g; s/;/\n/g; s/&/\n/g')
NL='
'
IFS="$NL"; set -- $segs; unset IFS
for seg in "$@"; do
  inspect $seg
done

exit 0
