# Documentation

## Overview {#overview}

Actor-Gatherer is a framework for agent design where agents context is managed proactively and externally using a Gatherer component. `ag` is a cli tool that turns any coding agent (Claude Code, Codex, OpenCode or Pi) into an actor-gatherer agent. The agent performing your tasks is called an Actor, and a **Gatherer** component manages the context of all actors connected to it. The Actors share all their messages with the Gatherer, and before every LLM call, they ask the Gatherer for their context. The Gatherer decides the context the model gets based on the current conversation, plus what matters from earlier history, from other agents, and from the environment.

<figure class="wide full"><img src="figures/architecture.png" alt="Actor-Gatherer architecture: each Actor, a harness plus its adaptor, calls insert and get_context on the Gatherer, which holds the context and insertion policy and a database; pollers watch the environment and insert events."><figcaption>Each Actor (a harness and its adaptor) sends what it sees and does to the Gatherer, and gets its context back before each model call. Pollers bring in changes from the environment, and the Gatherer's policy decides what context each Actor gets.</figcaption></figure>

The **Gatherer** is a server that many **Actors** talk to, and the Actors can come from different coding harnesses. An Actor is a harness plus its **adaptor**, which turns the harness's messages into events and the Gatherer's context back into messages. Each Actor uses two calls on the Gatherer:

- **`insert`** gives the Gatherer what the Actor has seen and done.
- **`get_context`** runs before each model call, and returns the context the model gets.

**Pollers** bring in information from the environment, such as files changed under the working directory. The Gatherer asks them for new events, and they insert those events like an Actor would. A **context management policy** inside the Gatherer then decides what context each Actor gets, using everything it has gathered from every Actor and from the environment.

`ag` currently uses:

- **Adaptors:** [`ClaudeAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/claude/adaptor/adaptor.py), [`CodexAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/codex/adaptor/adaptor.py), [`OpencodeAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/opencode/adaptor/adaptor.ts) and [`PiAdaptor`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/integrations/harnesses/pi/adaptor/adaptor.ts), each with the launcher `ag` uses to start that harness connected to the Gatherer.
- **Pollers:** [`FileChangePoller`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/ag_pollers/file_changes.py), which reports files changed under the agent's working directory since it last looked.
- **Context Policy:** [`ProactiveContextManager`](https://github.com/ucbepic/actor-gatherer/blob/main/ag/ag_policies/proactive_context_manager/policy.py), which searches earlier history in the background, and adds what other sessions asked for and what changed in the environment.

The framework is extensible. Add a new harness by defining an adaptor for it, new context policies for context management, and pollers that track other information in the environment. See [Extending `ag`](#extending).

## Install {#install}

<!-- gen: readme Install -->

## Quickstart {#quickstart}

<!-- gen: readme Quickstart -->

Every option and command is in [`ag` CLI interface](#cli).

## `ag` CLI interface {#cli}

`ag` is the command line that runs a harness with the Gatherer, and manages the gatherers and settings it keeps. Its options go before the harness's name, and everything after the name is passed to the harness unchanged.

### Options {#options}

By default every agent you start with `ag`, from any harness, joins one shared gatherer named `default` ([`[cli] gatherer`](#cli-settings)), each session as its own channel.

<!-- gen: options -->

A new gatherer takes its policy and pollers from the defaults in `config.toml`, or from `--policy` and `--poller` when given. They are recorded in `~/.ag/gatherers/<name>/gatherer.toml`, where you can change an existing gatherer's pollers, or override its policy's options under `[options]`. A gatherer's policy cannot change once it is in use; to try another, start a new gatherer.

<p class="note">The gatherer is chosen on every model call; it is not stored with the session. To resume a session in a named gatherer, name it again: <code>ag --gatherer demo codex resume &lt;id&gt;</code>. Without <code>--gatherer demo</code>, the resumed session goes into <code>default</code>.</p>

### Commands {#commands}

<!-- gen: commands -->

### The home directory {#home}

Everything `ag` keeps is in one directory, `~/.ag` (set `AG_HOME` to move it). Each gatherer has a directory of its own, with its settings and its database:

<!-- gen: home-layout -->

A gatherer's database records exactly what the model was sent on every call, so any context can be audited later. `ag gatherers` lists every gatherer, and `ag show <gatherer>` shows one's settings.

## Configuration {#configuration}

Every setting is in `~/.ag/config.toml`, created the first time you run `ag` with every default written out. A command-line option overrides the setting it names (`--gatherer` over `[cli] gatherer`), and so does an `AG_*` environment variable (`AG_LLM_MODEL` over `[policies.llm] model`). The file has these tables:

```toml
[policies]                     # the default policy
[policies.llm]                 # the LLM the policies call
[policies.available.<name>]    # the catalog: every policy a gatherer may use

[pollers]                      # the default pollers
[pollers.available.<name>]     # the catalog: every poller a gatherer may use

[cli]                          # the ag command: the default gatherer
[cli.harnesses.<name>]         # each harness ag can run
```

`ag config`, `ag home list` and `ag show` show how the settings resolve (see [Commands](#commands)).

### `[policies]` {#policies}

This is the `[policies]` part of the `config.toml` that `ag` writes on first run. `default` names the policy a new gatherer gets. Below it is the catalog, one `[policies.available.<name>]` entry per policy a gatherer may use: the shipped `proactive_context_manager`, and two commented-out entries to copy, a variant of it with other options (`pcm_small`) and a policy of your own from `~/.ag/plugins/` (`mine`).

<!-- gen: config policies -->

Each entry under `[policies.available.<name>]` makes a policy available under that name:

| key | meaning |
|---|---|
| `class` | `"module:Class"` for an importable class; or just `"Class"` together with `file` or `module`. A factory function works too. |
| `file` | A Python file in `~/.ag/plugins/` that defines `class`. |
| `module` | An importable module that defines `class`. |
| `options` | Options passed to the policy. A gatherer's own `[options]` in its `gatherer.toml` are applied on top of these. |

Two entries can name the same class with different options; each is a separate policy, and a gatherer picks one by name (`ag --gatherer small --policy pcm_small codex`).

### `[policies.llm]` {#llm}

The LLM the policy calls (to split history into tasks, summarize them, and rank them). There is no default model; set one here or with [`ag model`](#commands). The model's name decides how it is called:

- **A coding agent**, `claude-code/<model>` or `codex/<model>` (e.g. `claude-code/sonnet`): runs Claude Code (`claude -p`) or Codex for each call, on that agent's own login, with its tools and default instructions out of the way. No API key is needed, and every call counts against the subscription's limits. Codex models need OpenAI's Codex SDK: `pip install openai-codex`; `ag` refuses to run without it.
- **Any other name**, `provider/model` (e.g. `gemini/gemini-3.8-flash`): called through [LiteLLM](https://docs.litellm.ai/docs/providers), with the provider's API key.

<!-- gen: config policies.llm -->

<!-- gen: llm-settings -->

The Gatherer's own calls to Claude Code or Codex run without `ag`'s environment, so they never come back through `ag`.

### `[pollers]` {#pollers}

This is the `[pollers]` part of the `config.toml` that `ag` writes on first run. `default` lists the pollers a new gatherer gets. Below it is the catalog, one `[pollers.available.<name>]` entry per poller a gatherer may list: the shipped `file_changes`, and a commented-out entry to copy for a poller of your own from `~/.ag/plugins/` (`tickets`).

<!-- gen: config pollers -->

An entry under `[pollers.available.<name>]` takes `class`, `file` and `module` as for policies, and `args`: the arguments the poller is built with. In a string argument, `{cwd}` is the agent's working directory, `{gatherer}` the gatherer's name and `{home}` the `ag` home; `~` is expanded. A poller whose arguments need `{cwd}` is skipped when the request has no working directory.

A gatherer's pollers must output event types its policy accepts; `ag` checks this before each run (see [Events, event types and properties](#events)).

### `[cli]` {#cli-settings}

<!-- gen: config cli -->

`--gatherer` overrides it for one run (see [Options](#options)).

### `[cli.harnesses.<name>]` {#harnesses}

`ag` knows a harness only from its entry here, which names its launcher and its adaptor and holds the launcher's settings. `ag <name>` runs it. How each shipped harness is connected is in [The shipped harnesses](#connection-table).

<!-- gen: harness claude -->

<!-- gen: harness-keys -->

Environment variables for one harness, set when you run it:

<!-- gen: env harness -->

### Other environment variables {#env}

<!-- gen: env general -->

## Extending `ag` {#extending}

<!-- gen: doc ag.ag_interface -->

### Events, event types and properties {#events}

<!-- gen: doc ag.ag_interface.event -->

<!-- gen: doc ag.ag_policies.proactive_context_manager.events -->

### Writing a new context policy {#write-policy}

A policy is a subclass of `ag.ag_interface.Policy`:

<!-- gen: stub ag.ag_interface.policy:Policy name event_types init read bulk_loaded -->

<!-- gen: doc ag.ag_interface.policy:Policy -->

#### The store

What `read` and `init` get as `store`, beside the SQLite connection's own methods:

<!-- gen: stub ag.ag_interface.store:GathererStore rows event_types make_item made_items last_read high_water -->

### Writing a new poller {#write-poller}

A poller is a subclass of `ag.ag_interface.Poller`:

<!-- gen: stub ag.ag_interface.poller:Poller name id outputs properties poll -->

<!-- gen: doc ag.ag_interface.poller:Poller -->

### Adding a new harness {#write-adaptor}

<!-- gen: doc ag.integrations -->

#### Hook-based harnesses {#hook-based}

<!-- gen: doc ag.integrations Hook-based harnesses -->

#### Proxy-based harnesses {#proxy-based}

<!-- gen: doc ag.integrations Proxy-based harnesses -->

#### The shipped harnesses {#connection-table}

<!-- gen: doc ag.integrations.harnesses -->

#### The adaptor

<!-- gen: doc ag.integrations.tools.ag_orchestrator.adaptor:Adaptor -->

#### The hook

<!-- gen: doc ag.integrations.tools.ag_orchestrator.call_ag -->

#### The launcher

<!-- gen: doc ag.cli.launch:Launcher -->
