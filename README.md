<div align="center">

# The Actor-Gatherer Framework for AI Agents

[![Project page](https://img.shields.io/badge/Project%20page-actor--gatherer-blue)](https://ucbepic.github.io/actor-gatherer/)
[![Docs](https://img.shields.io/badge/Docs-actor--gatherer%2Fdocs-green)](https://ucbepic.github.io/actor-gatherer/docs.html)
[![Blog](https://img.shields.io/badge/Blog-read%20the%20post-purple)](https://ucbepic.github.io/actor-gatherer/blog.html)
[![Works with Claude Code, Codex, OpenCode and Pi](https://raw.githubusercontent.com/ucbepic/actor-gatherer/main/assets/works-with.svg)](#quickstart)

[What is the Actor-Gatherer Framework](#what-is-the-actor-gatherer-framework) · [Install](#install) · [Quickstart](#quickstart) · [Examples](#examples) · [How it works](#how-it-works) · [Extensions](#extensions)

</div>

---

## What is the Actor-Gatherer Framework

Actor-Gatherer is a new paradigm in agent design where the context across agents is managed proactively and externally, separating solving a task from context management needed to do so. 
An **Actor** (your coding agent: Claude Code, Codex, OpenCode or Pi) works on
the task. A **Gatherer** (also AI-powered) monitors the Actor, other agents and the environment,
and before every model call decides what context the Actor gets. The Gatherer:

- **Shares information across agents:** Actors using the same Gatherer can benefit from each other’s work, even when they run on different harnesses,
- **Keeps context relevant:** It identifies what's relevant for the current task from past interactions, paging in useful information and removing redundant details, and
- **Tracks the environment:** If a file the Actor relies on changes, the Gatherer surfaces the update before the Actor acts on outdated information.

Without a Gatherer, each agent operates largely on its own history, which is typically summarized as it grows. This can leave agents unaware of relevant past interactions, work done by other agents, or changes made by the user.


---

## Install

You need Python 3.11+ and the harness you want to run on your `PATH`. Install `ag` from PyPI:

```bash
pip install actor-gatherer
```

To use a Codex model as the Gatherer's LLM (`codex/<model>`, [below](#set-the-gatherers-llm)),
install it with the Codex SDK instead:

```bash
pip install "actor-gatherer[codex]"
```

Or from source:

```bash
git clone https://github.com/ucbepic/actor-gatherer && cd actor-gatherer
pip install -r requirements.txt        # `ag` from this clone, editable, with every dependency
```

### Set the Gatherer's LLM

It can be an API-based model, called through
[LiteLLM](https://docs.litellm.ai/docs/providers). Name it as `provider/model`, and set that provider's API key, e.g.,

```bash
ag model openai/gpt-6-sol                    # "provider/model"; the key from OPENAI_API_KEY
export OPENAI_API_KEY=...

ag model gemini/gemini-3.8-flash             # or a Gemini model; the key from GEMINI_API_KEY
export GEMINI_API_KEY=...
```

Or it can be a coding agent, such as Claude Code or Codex, named as

```bash
ag model claude-code/sonnet
ag model codex/gpt-6-sol
```

which runs Claude Code or Codex for the Gatherer, on its own login. Codex models need the
Codex SDK, from `pip install "actor-gatherer[codex]"` (a clone's `pip install -r requirements.txt`
includes it); Claude Code models need only `claude` on your `PATH`.

To check the model that is set:

```bash
ag model
```

## Quickstart

Put `ag --gatherer NAME` in front of the agent command you would normally run.

```bash
ag --gatherer demo claude                                # Claude Code
ag --gatherer demo codex exec "fix the tests"            # Codex
ag --gatherer demo opencode run "add a --verbose flag"   # OpenCode
ag --gatherer demo pi                                    # Pi
```
Agents join the gatherer specified (`demo` above).  Agents with the same gatherer 
share information with each other, whichever harness runs them (see the [example](#awareness-across-agents) below). Agents in
different gatherers don't share context and each gatherer keeps its own history.

For example, the first two agents below share information; the third, in a
gatherer of its own, sees neither of them:

```bash
ag --gatherer frontend claude                            # shares with the Codex below
ag --gatherer frontend codex                             # shares with the Claude Code above
ag --gatherer backend codex                              # shares with neither
```

Without `--gatherer`, a session joins the gatherer `default`:

```bash
ag codex                                                 # the same as: ag --gatherer default codex
```

Use `--gatherer .` to create a new, unnamed gatherer. Agents created
this way don't share context with other agents:

```bash
ag --gatherer . codex
```

To see every gatherer:

```bash
ag gatherers                                             # each one's policy, pollers, event count, last activity
```

## Examples

The Actor-Gatherer framework improves accuracy in three settings:

- **Long-running sessions:** the Gatherer decides what matters from a long history
  for the task at hand, pages in relevant information when needed and removes irrelevant ones.
- **Sharing information across parallel agents:** agents in the same gatherer,
  even in different harnesses, get what they need from each other's work.
- **Observing the environment:** when something an agent relied on changes, such
  as a file, the Gatherer tells it before it answers from a stale copy.

Below are two short examples of the latter two.

### Awareness across agents

`ag` proactively shares information across agents when one needs it, as long as
they are in the same gatherer, even if they run in different harnesses.

For example, start a Codex session in a gatherer named `demo`:

```bash
ag --gatherer demo codex "Let X = 5. What is 2X?"
```
```
If X = 5, then 2X = 2 × 5 = 10.
```

Then start Claude Code in the same gatherer, in another terminal or after the
first has ended:

```bash
ag --gatherer demo claude "What is 3X?"
```
```
3X = 15.

Your question doesn't define X, so I took X = 5 from your message to the other
agent ("Let X = 5. What is 2X?").
```

Claude Code never saw the Codex session. Both are in `demo`, so the Gatherer
gave it Codex's request, and told it where to read the rest of that session's
work.

### Information from the environment

`ag` observes the agent's environment, such as the files in its working
directory, and tells the agent when something it relied on has changed. The
example's data file is in this repo, at [`demo/salaries.csv`](https://github.com/ucbepic/actor-gatherer/blob/main/demo/salaries.csv).

**1. Copy the demo file,** so your edit leaves the repo's copy as it is, and
start Codex next to it:

```bash
mkdir -p /tmp/ag-salaries && cp demo/salaries.csv /tmp/ag-salaries/ && cd /tmp/ag-salaries
ag --gatherer salaries codex
```

**2. Ask, in Codex:**

```
> I'm putting together a compensation benchmark from salaries.csv. Where does
  Germany's average salary sit relative to the median of the countries listed?

Germany ($58,940) sits $3,820 above the median ($55,120, the United Kingdom).
```

**3. Change the file while the session stays open.** In another terminal,
change Japan from 42,180 to 47,152 (or edit the file by hand):

```bash
f=/tmp/ag-salaries/salaries.csv; c=$(<"$f"); printf '%s\n' "${c/Japan,42180,/Japan,47152,}" > "$f"
```

**4. Ask, in the same Codex session:**

```
> How large is the gap between France and Japan, in USD?

France: $49,310. Japan: $47,152. The gap between France and Japan is $2,158.
```

Before this question reached the model, the Gatherer told Codex that
`salaries.csv` had changed after it last read it, so Codex read the file again.

**To compare,** repeat the steps with plain `codex`, starting from a fresh copy
(`mkdir -p /tmp/plain-salaries && cp demo/salaries.csv /tmp/plain-salaries/ && cd /tmp/plain-salaries && codex`). It
answers $7,130, which is incorrect: it uses Japan's old value from its first read.

## How it works

![Actor-Gatherer architecture: each Actor (a harness plus its adaptor) calls insert and get_context on the Gatherer, which holds the context and insertion policy and a database; pollers watch the environment and insert events](https://raw.githubusercontent.com/ucbepic/actor-gatherer/main/assets/architecture.png)

The **Gatherer** is a server that many **Actors** talk to, and the Actors can come
from different coding harnesses. An Actor is a harness plus its **adaptor**, which
turns the harness's messages into a unified data representation and the Gatherer's context back into
message format the harness supports. Each Actor uses two calls on the Gatherer:
- **`insert`** gives the Gatherer what the Actor has seen and done.
- **`get_context`** runs before each model call, and returns the context the model gets.

**Pollers** bring in information from the environment, such as files changed under
the working directory. The Gatherer asks them for new events in the environment, and they insert
those events like an Actor would. A **context management policy** inside the
Gatherer then decides what context each Actor gets, using everything it has
gathered from every Actor and from the environment.

`ag` currently uses:
- **Adaptors:** [`ClaudeAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/claude/adaptor/adaptor.py),
  [`CodexAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/codex/adaptor/adaptor.py),
  [`OpencodeAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/opencode/adaptor/adaptor.ts) and
  [`PiAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/pi/adaptor/adaptor.ts), each with the
  launcher `ag` uses to start that harness connected to the Gatherer.
- **Pollers:** [`FileChangePoller`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/ag_pollers/file_changes.py),
  which reports files changed under the agent's working directory since it last
  looked.
- **Context Policy:** [`ProactiveContextManager`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/ag_policies/proactive_context_manager/policy.py),
  which searches earlier history in the
  background, and adds what other sessions asked for and what changed in the
  environment.

## Extensions

`ag` is extensible. You can:

- write your own [context policy](https://ucbepic.github.io/actor-gatherer/docs.html#write-policy), which decides what the
  agent's context holds,
- write your own [poller](https://ucbepic.github.io/actor-gatherer/docs.html#write-poller), which brings in information from the
  environment, or
- [add a harness](https://ucbepic.github.io/actor-gatherer/docs.html#write-adaptor), so another coding agent can run with `ag`.

See [Extending ag](https://ucbepic.github.io/actor-gatherer/docs.html#extending) in the docs.
