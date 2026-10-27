"""The harness, run by ag's launcher, with its calls passed through a tap (tap.py) on their way to ag's hook server --
the probe's `[cli.harnesses.<name>] command` (probe.py): `python wrap.py <harness> <args...>`.

The hook server's address is where ag's launcher put it -- Claude Code's ANTHROPIC_BASE_URL, codex's `-c
openai_base_url=...` argument -- and is changed to the tap's, which relays to it, path and all. One tap per hook
server, started on first use and kept (its port in $PROBE_DIR/taps/<hook port>.port). A run whose address is not a
hook server's (the launcher's own `/context` probe of Claude Code) runs as it is. The harness is exec'd: its process
is this one, as the launcher named it."""

import os
import re
import subprocess
import sys
import time

HOOK = re.compile(r"http://127\.0\.0\.1:(\d+)(?=/h/)")


def tap_for(port: str) -> str:
    """The tap's port for the hook server on `port`, started if it is not running."""
    root = os.environ["PROBE_DIR"]
    os.makedirs(os.path.join(root, "taps"), exist_ok=True)
    port_file = os.path.join(root, "taps", f"{port}.port")
    if not os.path.exists(port_file):
        subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tap.py"),
                          "--target", f"http://127.0.0.1:{port}", "--out", os.path.join(root, "calls.jsonl"),
                          "--port-file", port_file, "--fail", os.environ.get("PROBE_FAIL", "")],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=open(os.path.join(root, "taps", f"{port}.log"), "a"), start_new_session=True)
        for _ in range(100):
            if os.path.exists(port_file):
                break
            time.sleep(0.1)
    with open(port_file) as fh:
        return fh.read().strip()


def main() -> None:
    argv, env = sys.argv[1:], dict(os.environ)
    url = env.get("ANTHROPIC_BASE_URL", "")
    if HOOK.search(url):
        env["ANTHROPIC_BASE_URL"] = HOOK.sub(lambda m: f"http://127.0.0.1:{tap_for(m.group(1))}", url)
    argv = [HOOK.sub(lambda m: f"http://127.0.0.1:{tap_for(m.group(1))}", a) if "openai_base_url=" in a else a
            for a in argv]
    os.execvpe(argv[0], argv, env)


if __name__ == "__main__":
    main()
