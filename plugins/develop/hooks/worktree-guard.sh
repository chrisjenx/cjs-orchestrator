#!/usr/bin/env sh
# worktree-guard — a safe, STACK-AGNOSTIC PreToolUse(Bash) guard for the develop flow.
#
# Blocks two classes of mistake that can destroy other phases' work or the user's
# workspace. It knows nothing about any language, build tool, or framework — it only
# reasons about git and worktrees, so it is safe to install in any repo.
#
# Hook protocol: reads the tool-call JSON on stdin, exits 0 to allow, exits 2 (with a
# reason on stderr) to block.

input=$(cat)

# Extract the Bash command. Prefer python3 (precise); fall back to matching raw stdin.
cmd=""
if command -v python3 >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print((d.get("tool_input") or {}).get("command",""))
except Exception:
    pass' 2>/dev/null)
fi
[ -z "$cmd" ] && cmd="$input"

# 1) Destructive git that can wipe uncommitted or sibling-phase work.
#    Read-only git is always fine; these specific mutating forms are not.
case "$cmd" in
  *"git checkout"*|*"git restore"*|*"git reset --hard"*|*"git clean "*|*"git clean"|*"git stash"*)
    echo "develop:worktree-guard — refusing destructive git ('$cmd')." >&2
    echo "The develop flow uses read-only git; checkout/restore/reset --hard/clean/stash can" >&2
    echo "destroy other phases' uncommitted work. If you really need this, run it yourself." >&2
    exit 2
    ;;
esac

# 2) Mutating work on the default branch. Feature work belongs on a worktree branch.
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
  case "$cmd" in
    *"git commit"*|*"git push"*|*"git merge"*|*"git rebase"*)
      echo "develop:worktree-guard — refusing '$cmd' on '$branch'." >&2
      echo "Create/enter a worktree branch first (the develop loop does this in step 2)." >&2
      exit 2
      ;;
  esac
fi

exit 0
