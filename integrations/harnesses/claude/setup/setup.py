"""Setting the context manager up in Claude Code. Claude Code has no hook that can replace its
messages, so its setup is the hook server (integrations/tools/hook_server/hook_server.py) calling the
context manager as Claude Code's hook (ag_orchestrator/context_manager.py) on every request,
relaying each to the API's endpoint:

    claude --(Anthropic Messages API)--> :<port> this --> <upstream>
                                              |
                                  claude's context manager --(stdio)--> context manager server, one per gatherer

    python -m integrations.harnesses.claude.setup.setup --port 4113 --upstream https://api.anthropic.com [--log-dir DIR]
                                    [--option cwd=DIR] [--option adaptor=module:Class] ...

Claude Code is then pointed at it by ANTHROPIC_BASE_URL="http://127.0.0.1:<port>[/h/<gatherer>]" (it
appends /v1/messages); `ag claude` (launch.py) does that for one run. A `/h/<gatherer>/` prefix names
the gatherer, each Claude Code session a channel in it (`claude --session-id <uuid>` chooses the
session); without one, each session is a gatherer of its own. Every flag but --hook is the hook server's; it needs `aiohttp`.
"""

import sys

from integrations.tools.hook_server import hook_server

HOOK = "integrations.harnesses.claude.ag_orchestrator.context_manager:ClaudeContextManager"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    return hook_server.main(["--hook", HOOK, *argv])


if __name__ == "__main__":
    sys.exit(main())
