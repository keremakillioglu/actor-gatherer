"""Setting the context manager up in codex. Codex has no hook that can replace
what it sends its model, so its setup is the hook server
(ag/integrations/tools/hook_server/hook_server.py) calling the context manager as
codex's hook (ag_orchestrator/context_manager.py) on every request, relaying
each to the provider's endpoint:

    codex --(Responses API)--> :<port> this --> <upstream>
                                    |
                              codex's context manager --(stdio)--> context manager server, one per gatherer

    python -m ag.integrations.harnesses.codex.setup.setup --port 4013 --upstream <provider origin> [--log-dir DIR]
                                    [--option cwd=DIR] [--option factory=module:attr] ...

Codex is then pointed at it by its provider's base_url, the upstream's path
kept: `-c model_providers.<name>.base_url="http://127.0.0.1:<port>[/h/<gatherer>]/v1"`.
`ag codex` (launch.py) does that for one run, starting this if it is not
running. A `/h/<gatherer>/` prefix names the gatherer, each codex thread a
channel in it; without one, each thread is a gatherer of its own.

Every flag but --hook is the hook server's; it needs `aiohttp`.
"""

import sys

from ag.integrations.tools.hook_server import hook_server

HOOK = "ag.integrations.harnesses.codex.ag_orchestrator.context_manager:CodexContextManager"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    return hook_server.main(["--hook", HOOK, *argv])


if __name__ == "__main__":
    sys.exit(main())
