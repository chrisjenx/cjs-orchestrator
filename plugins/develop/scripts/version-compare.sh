#!/usr/bin/env sh
# version-compare.sh <a> <b> — echo exactly one of: older | same | newer  (a relative to b).
# POSIX sh only — no bashisms: no <<< here-strings, no arrays, no `local`, no $((10#$n)).
# Missing components default to 0 (so 0.9 == 0.9.0); per-component NUMERIC compare with early
# exit (so 0.10.0 is newer than 0.9.0, not lexical). A non-numeric suffix on a component is
# ignored (only its leading integer counts).
set -f
a=$1
b=$2
if [ -z "$a" ] || [ -z "$b" ]; then
  echo "usage: version-compare.sh <a> <b>" >&2
  exit 3
fi

# Split each version into up to 4 components via a POSIX heredoc (NEVER <<<).
read a1 a2 a3 a4 <<EOF
$(printf '%s' "$a" | tr '.' ' ')
EOF
read b1 b2 b3 b4 <<EOF
$(printf '%s' "$b" | tr '.' ' ')
EOF

num() {  # echo the leading integer of $1, or 0
  n=$(printf '%s' "$1" | sed 's/[^0-9].*$//')
  if [ -n "$n" ]; then echo "$n"; else echo 0; fi
}

for pair in "$(num "$a1") $(num "$b1")" "$(num "$a2") $(num "$b2")" \
            "$(num "$a3") $(num "$b3")" "$(num "$a4") $(num "$b4")"; do
  x=${pair% *}
  y=${pair#* }
  if [ "$x" -gt "$y" ]; then echo newer; exit 0; fi
  if [ "$x" -lt "$y" ]; then echo older; exit 0; fi
done
echo same
exit 0
