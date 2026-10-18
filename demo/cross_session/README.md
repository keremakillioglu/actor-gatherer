# The cross-session example

Two Claude Code sessions in one folder, run once with `ag` and once without, to
compare what the second session knows of a choice the user made in the first.

```bash
demo/cross_session/run.sh ag       # Claude Code under ag
demo/cross_session/run.sh plain    # Claude Code alone
```

Each prints the second session's answer, the joins its queries used, and any
memory Claude Code saved. Every turn is a real model call, so a run takes a few
minutes.

## The sessions

`make_db.py` builds `studios.sqlite`, a TV catalogue with schema ambiguity: the
catalogue can be linked to its studios through two columns that both match every
row, the declared foreign key `catalogue.studio_id -> companies.company_id` and
`catalogue.feed_tag = companies.callsign`. They disagree for four studios. In this
data `feed_tag` is right; four studios' ids in `studio_id` are swapped.

Session 1, four turns:

1. "In studios.sqlite, which studios have the most catalogue entries? Top five,
   name and count." Nothing says which join to use.
2. "Which genres are most common across the catalogue? Give counts."
3. "Join catalogue to companies on catalogue.feed_tag = companies.callsign and
   give the top five studios by catalogue entries, name and count."
4. "Reply with a short report with exactly these fields: …", ending in
   "National Broadcasting entries: 105". 105 is the `feed_tag` figure; joining on
   `studio_id` gives 70. The report is in the reply, not a file, so the folder
   holds nothing of the choice.

Session 2, a new session in the same folder: "Which five studios have the most
Drama entries? Name and count." Joining on `feed_tag` puts National Broadcasting
first, with 46; joining on `studio_id` puts Columbia Broadcasting first.

## What session 2 has of session 1

- **plain:** the folder (`studios.sqlite`), and Claude Code's memory of the folder
  (`~/.claude/projects/<folder>/memory/`) if session 1 saved one.
- **ag:** the same, and the gatherer: session 2 is told the requests the user made
  in session 1, and where to read session 1's work.

## Options

- `run.sh ag|plain [out_dir]`: logs go to `out_dir` (default: a new temporary
  directory). The sessions run in a new temporary folder, `tv-analytics`, and in
  `ag` mode the gatherer is the default one of a new scratch `AG_HOME`. Both are
  apart from the logs, and their paths, which the agent sees, say nothing of the
  example.
- `CLAUDE_ARGS`: extra arguments for every Claude Code call, e.g.
  `CLAUDE_ARGS="--model sonnet"`.
- `AG`: the `ag` command, if it isn't `ag` on your `PATH`.
- `PYTHON`: a Python 3.11 or later, if `python3` isn't one.

In `ag` mode, `setup_home.py` makes a scratch `AG_HOME` for the run. It takes the
Gatherer's LLM from your own `ag` config, which it leaves as it is; everything
else is `ag`'s default.
