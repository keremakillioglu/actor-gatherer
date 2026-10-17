r"""Each harness's own integration, one package per harness: its hook (ag_orchestrator/), its
adaptor (adaptor/), and its setup and launcher (setup/).

| harness | type | what the launcher does | gatherer | channel | the Gatherer's own messages arrive as | turned off |
|---|---|---|---|---|---|---|
| Pi | hook | Loads the extension with `-e`, unless Pi already has the package installed. | `--ag-gatherer NAME` | the session | a hidden custom message | Pi's compaction |
| OpenCode | hook | Adds the plugin through `OPENCODE_CONFIG_CONTENT`. | the plugin's `gatherer` option | the session | a synthetic user message | auto-compaction and tool-output pruning |
| Claude Code | proxy | Starts a proxy if none is running for the upstream, and points `ANTHROPIC_BASE_URL` at it. | URL path `/h/<gatherer>/` | the session | system messages, or user-turn reminders (`system_messages`) | nothing |
| Codex | proxy | Starts a proxy if none is running for the upstream, and points the active provider's `base_url` at it (`-c`). | URL path `/h/<gatherer>/` | the thread | developer messages (`AG_CODEX_AG_ROLE=user`: user messages) | nothing |
"""
