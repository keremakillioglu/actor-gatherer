#!/usr/bin/env bash
# run.sh ag|plain [out_dir]: the cross-session example. Session 1, four Claude Code turns in a folder with
# studios.sqlite: the top five studios, the genres, the top five joined on feed_tag = callsign, and a report,
# in the reply, that uses that join's figure for National Broadcasting (105). Session 2, a new Claude Code
# session in the same folder, asks for the top five studios by Drama entries.
#   ag      both sessions under ag, in the default gatherer of a scratch AG_HOME (setup_home.py)
#   plain   Claude Code alone
# The folder (and the scratch AG_HOME) are new temporary directories, apart from the logs, which go to out_dir
# (default: a new temporary directory too). It prints session 2's answer, the joins its queries used, and any
# memory Claude Code saved. Every turn is a real model call, on the model your Claude Code uses; CLAUDE_ARGS
# adds arguments to every call, e.g. CLAUDE_ARGS="--model sonnet". AG names the ag command (default: ag);
# PYTHON a Python 3.11+ (default: python3).
set -u
MODE=${1:?usage: run.sh ag|plain [out_dir]}
case $MODE in ag|plain) ;; *) echo "usage: run.sh ag|plain [out_dir]" >&2; exit 2 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
LOGS=${2:-$(mktemp -d)}
mkdir -p "$LOGS" && LOGS=$(cd "$LOGS" && pwd -P)
AG=${AG:-ag}
PY=${PYTHON:-python3}
read -r -a EXTRA <<< "${CLAUDE_ARGS:-}"
fresh() { local d; d=$(mktemp -d) && cd "$d" && pwd -P; }
# The agent sees its folder's path, and under ag its gatherer's: both are fresh, neutral and apart from the logs.
WORK=$(fresh)/tv-analytics
mkdir -p "$WORK"
# Claude Code keeps a folder's sessions and memory under ~/.claude/projects/<folder, non-alphanumerics as ->
PROJ=$HOME/.claude/projects/$(printf '%s' "$WORK" | sed 's/[^A-Za-z0-9]/-/g')
$PY "$HERE/make_db.py" "$WORK/studios.sqlite"

FLAGS=(-p --output-format json --permission-mode acceptEdits
       --allowedTools "Bash(sqlite3:*)" "Bash(python3:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Read" "Write" "Edit"
       ${EXTRA[@]+"${EXTRA[@]}"})
if [ "$MODE" = ag ]; then
  YOURS=$($AG model | sed -nE 's/^config: +//p')
  HOME_DIR=$(fresh)/.ag
  $PY "$HERE/setup_home.py" "$AG" "$YOURS" "$HOME_DIR" || exit 1
  export AG_HOME=$HOME_DIR
  RUN=($AG claude "${FLAGS[@]}")               # its default gatherer
else
  RUN=(claude "${FLAGS[@]}")
fi
field() { $PY -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

cd "$WORK"
SID=""
turn() {  # turn <name> <message>: in session 1, or a new session for "session2"
  if [ -z "$SID" ] || [ "$1" = session2 ]; then
    printf '%s' "$2" | "${RUN[@]}" >"$LOGS/$1.json" 2>"$LOGS/$1.err"
  else
    printf '%s' "$2" | "${RUN[@]}" --resume "$SID" >"$LOGS/$1.json" 2>"$LOGS/$1.err"
  fi
  field "$LOGS/$1.json" result >"$LOGS/$1.out" 2>/dev/null
  [ -s "$LOGS/$1.out" ] || { echo "turn $1: no answer, see $LOGS/$1.err" >&2; exit 1; }
  [ -n "$SID" ] || SID=$(field "$LOGS/$1.json" session_id)
  echo "turn $1 done"
}

turn 1 "In studios.sqlite, which studios have the most catalogue entries? Top five, name and count."
turn 2 "Which genres are most common across the catalogue? Give counts."
turn 3 "Join catalogue to companies on catalogue.feed_tag = companies.callsign and give the top five studios by catalogue entries, name and count."
turn 4 "Reply with a short report with exactly these fields:
- Title: Catalogue Report
- Total entries: 704
- Genre counts (table with columns Genre, Entries): Drama 143, Comedy 104, Reality 97, News 96, Documentary 95, Animation 90, Kids 79
- National Broadcasting entries: 105"
echo "folder after session 1: $(ls "$WORK" | tr '\n' ' ')"
turn session2 "Which five studios have the most Drama entries? Name and count."
S2=$(field "$LOGS/session2.json" session_id)

echo
echo "=== session 2's answer"
cat "$LOGS/session2.out"
echo "=== joins in session 2's queries:"
$PY - "$PROJ/$S2.jsonl" <<'EOF'
import json, re, sys
calls = [json.dumps(b.get("input")) for l in open(sys.argv[1]) if l.strip()
         for r in [json.loads(l)] if r.get("type") == "assistant"
         for b in r["message"].get("content", []) if isinstance(b, dict) and b.get("type") == "tool_use"]
print(" ".join(sorted({" ".join(m.group(0).split()) for c in calls for m in re.finditer(r"ON\s+[\w.]+\s*=\s*[\w.]+", c, re.I)})))
EOF
echo "(correct: feed_tag = callsign, with National Broadcasting first at 46; studio_id puts Columbia Broadcasting first)"
echo "=== memory Claude Code saved: $(ls "$PROJ/memory" 2>/dev/null | tr '\n' ' ')"
echo "folder: $WORK"
echo "logs: $LOGS"
[ "$MODE" = ag ] && $AG stop >/dev/null
exit 0
