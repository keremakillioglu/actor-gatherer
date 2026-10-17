r"""The harness side: how each harness reaches the Gatherer. It imports nothing of the context
manager, and reaches it through its server, over stdio.

Connecting a new harness takes three pieces:

- An **adaptor** turns the harness's messages into events, and the context back into messages.
- A **hook** in the harness calls the Gatherer before each model call.
- A **launcher** starts the harness with that hook in place, for one run.

The hook is the harness's own, if it has one; otherwise a proxy stands in for it. Nothing
the harness reads on disk is changed: each change (an environment variable, a flag, a local
proxy) applies to that one run, and the same command without `ag` behaves as it always did.
If the Gatherer fails or times out, the harness sends its own messages unchanged.

Hook-based harnesses
--------------------

A harness with a plugin system that can change the messages before each model call is
connected through a **hook**: a plugin that `ag` loads into the harness. Pi (an extension)
and OpenCode (a plugin) are connected this way.

- The launcher loads the plugin for this run only: a command-line flag for Pi, and the
  configuration passed in the environment for OpenCode.
- Before every model call, the harness calls the plugin's hook with the messages. The plugin
  runs the adaptor, sends the events to the Gatherer, and gives the harness back the context
  to send instead.
- The gatherer is passed to the plugin as an option, and the channel is the harness's session.
- The harness's own compaction is turned off while the Gatherer answers, since the Gatherer
  now decides what the context holds. Set `AG_PI_COMPACTION=allow` or
  `AG_OPENCODE_COMPACTION=allow` to keep it on.

Proxy-based harnesses
---------------------

A harness without such a hook is connected through a **proxy**: a local server that sits
between the harness and its model's API, and changes each model call on its way there. This
works for any harness that calls its model over HTTP and lets you change where those calls
go. Claude Code and Codex are connected this way.

- The launcher points the harness's API base URL at the proxy, for this run only. The proxy
  relays to wherever the harness pointed before (the *upstream*).
- On every request that is a model call, the proxy runs the adaptor on the request's
  messages, sends the events to the Gatherer, and forwards the request with the context in
  place of the messages. Every other request passes through untouched, and the answer
  streams back unchanged.
- The gatherer is passed in the URL path, `/h/<gatherer>/`, and the channel is the harness's
  session (a Claude Code session, a Codex thread), read from the request.
- Proxies run detached: the first run with a given upstream starts one, and later runs and
  other sessions reuse it. `ag status` lists them and `ag stop` stops them.
"""
