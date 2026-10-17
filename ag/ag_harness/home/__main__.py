"""The context manager's home, from the command line.

    python -m ag.ag_harness.home path                 where it is (AG_HOME, or ~/.ag)
    python -m ag.ag_harness.home list                 every policy and poller, and any problem
    python -m ag.ag_harness.home gatherers                every gatherer: its policy, pollers, events, last activity
    python -m ag.ag_harness.home show <gatherer>          a gatherer's config, as it resolves
    python -m ag.ag_harness.home new <gatherer> [--policy P] [--poller X ... | --no-pollers] [--force]
                                                        make a gatherer's config ahead of use
    python -m ag.ag_harness.home model [NAME] [--api-base URL] [--key-env VAR]
                                                        the LLM the policies call: shown, or set in
                                                        config.toml ([policies.llm]) for every gatherer
    python -m ag.ag_harness.home contract [--gatherer S] [--policy P] [--poller X ... | --no-pollers]
                                                        what a run would take, as JSON: the policy,
                                                        its event types, each poller's outputs

`ag home ...` runs the same.
"""

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import sys

from ag.ag_interface import property_column
from ..store import paths, schema
from . import CLI_MODELS, ConfigError, GathererConfig, home


def cmd_list(h) -> int:
    policies, pollers = h.policies(), h.pollers()
    default = h.default_policy()
    print(f"home: {h.root}")
    print("\npolicies:")
    for spec in policies.values():
        mark = "  (default)" if spec.name == default else ""
        print(f"  {spec.name:18s} {spec.origin:34s}{mark}")
        if spec.options:
            print(f"  {'':18s} options: {spec.options}")
    print(f"\npollers:  (a new gatherer's: {', '.join(h.default_pollers()) or '-'})")
    for spec in pollers.values():
        try:
            cls = h.poller_class(spec)
            outputs = ", ".join(cls.outputs)
            sets = ", ".join(getattr(cls, "properties", ())) or "-"
        except ConfigError:
            outputs, sets = "?", "?"
        print(f"  {spec.name:18s} {spec.origin:34s} outputs: {outputs:20s} sets: {sets:8s} args: {spec.args}")
    problems = h.problems()
    print("\nproblems:" if problems else "\nno problems")
    for line in problems:
        print(f"  {line}")
    return 1 if problems else 0


def gatherer_stats(gatherer: str) -> dict:
    """What a gatherer's database holds, read without writing to it: its events,
    when the last was stored, and how many distinct values each property
    has (e.g. its channels); {} with no database."""
    path = paths.db_path(gatherer)
    if not os.path.exists(path):
        return {}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=8)
    try:
        events, last = conn.execute("SELECT count(*), max(inserted_at) FROM events").fetchone()
        values = {name: conn.execute(f"SELECT count(DISTINCT {property_column(name)}) FROM events").fetchone()[0]
                  for name in schema.property_names(conn)}
        return {"events": events, "last": last, "properties": values}
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    finally:
        conn.close()


def cmd_gatherers(h) -> int:
    """Every gatherer in the home, newest activity first."""
    root = paths.TRACE_DIR
    names = sorted(n for n in os.listdir(root) if os.path.isfile(os.path.join(root, n, "gatherer.toml"))) \
        if os.path.isdir(root) else []
    if not names:
        print(f"no gatherers in {root}")
        return 0
    rows = []
    for name in names:
        try:
            cfg = h.gatherer(name, create=False)
            policy, pollers = cfg.policy, ", ".join(cfg.pollers) or "-"
        except ConfigError as exc:
            policy, pollers = "?", str(exc)
        rows.append((name, policy, pollers, gatherer_stats(name)))
    rows.sort(key=lambda r: r[3].get("last") or "", reverse=True)
    print(f"gatherers in {root}:")
    width = max(len(r[0]) for r in rows)
    for name, policy, pollers, stats in rows:
        if "error" in stats:
            about = f"database unreadable: {stats['error']}"
        elif not stats:
            about = "no database yet"
        else:
            seen = ", ".join(f"{n} {c}" for n, c in stats["properties"].items() if c) or "-"
            last = (stats["last"] or "")[:16].replace("T", " ")
            about = f"{stats['events']} events, last {last or '-'} UTC; distinct {seen}"
        print(f"  {name:{width}s}  {policy:14s} pollers: {pollers:14s} {about}")
    return 0


def cmd_show(h, gatherer: str) -> int:
    cfg = h.gatherer(gatherer, create=False)
    print(f"gatherer:    {gatherer}\nconfig:  {cfg.path}\ndatabase: {paths.db_path(gatherer)}"
          f"{'' if os.path.exists(paths.db_path(gatherer)) else '  (not yet)'}")
    print(f"policy:  {cfg.policy}" + (f"  (read with {h.locked_policy(gatherer)})" if h.locked_policy(gatherer) else ""))
    if cfg.options:
        print(f"options: {cfg.options}")
    known = h.pollers()
    print("pollers:")
    for name in cfg.pollers:
        spec = known.get(name)
        print(f"  {name:18s} " + (f"{spec.origin}  args: {spec.args}" if spec else "NOT KNOWN"))
    return 0


def cmd_new(h, gatherer: str, policy, pollers, force: bool, none: bool = False) -> int:
    path = h.gatherer_path(gatherer)
    if os.path.exists(path) and not force:
        print(f"{path} exists (--force to replace it)", file=sys.stderr)
        return 1
    policy = policy or h.default_policy()
    spec = h.policies().get(policy)
    if spec is None:
        print(f"no policy {policy!r}; `list` shows them", file=sys.stderr)
        return 1
    chosen = [] if none else (list(pollers) if pollers else h.default_pollers())
    unknown = [p for p in chosen if p not in h.pollers()]
    if unknown:
        print(f"no poller {', '.join(unknown)}; `list` shows them", file=sys.stderr)
        return 1
    h.write_gatherer(GathererConfig(gatherer, policy, chosen, {}, path))
    print(path)
    return 0


def contract(h, gatherer, policy, pollers, none: bool = False) -> dict:
    """What a run takes: the policy -- the gatherer's, if it exists, else
    `policy` or the default -- its event types (with their properties), and
    the outputs of each poller, and the properties each sets
    (`pollers`, else the gatherer's, else [pollers] default)."""
    cfg = h.gatherer(gatherer, create=False) if gatherer and os.path.exists(h.gatherer_path(gatherer)) else None
    policy = policy or (cfg.policy if cfg else h.default_policy())
    spec = h.policies().get(policy)
    if spec is None:
        raise ConfigError(f"no policy {policy!r}; `list` shows them")
    names = [] if none else (list(pollers) if pollers else (list(cfg.pollers) if cfg else h.default_pollers()))
    source = "given" if (none or pollers) else ("gatherer" if cfg else "default")
    known = h.pollers()
    unknown = [p for p in names if p not in known]
    if unknown:
        raise ConfigError(f"no poller {', '.join(unknown)}; `list` shows them")
    return {"policy": policy,
            "event_types": [{"name": t.name, "properties": [{"name": p.name, "required": p.required}
                                                            for p in t.properties]}
                            for t in h.policy_class(spec).event_types],
            "pollers": {name: list(h.poller_class(known[name]).outputs) for name in names},
            "poller_properties": {name: list(getattr(h.poller_class(known[name]), "properties", ()))
                                  for name in names},
            "pollers_from": source,                                   # given, the gatherer's, or [pollers] default
            "model": h.model(),                                       # the LLM's; "": none set
            "llm_problem": h.llm_problem()}                           # why it cannot run here; "": none
def cmd_model(h, model, api_base, key_env) -> int:
    """[policies.llm]: set what is given (a flag left out stays; "" removes it), then
    show it, and what overrides it from the environment."""
    if model is not None and not model.strip():
        print("the model cannot be empty: name one, e.g. gemini/gemini-3.8-flash", file=sys.stderr)
        return 1
    if (model, api_base, key_env) != (None, None, None):
        h.set_llm(model, api_base, key_env)
    cfg = h._llm_config()
    base = h.api_base_of(cfg.get("api_base") or cfg.get("url"))
    key_env = str(cfg.get("key_env") or ("LITELLM_KEY" if cfg.get("url") else ""))
    print(f"model:     {cfg.get('model') or '(none set: every call fails until one is)'}")
    cli = str(cfg.get("model") or "").partition("/")[0]
    if cli in CLI_MODELS and not cfg.get("class"):
        command = str(cfg.get(f"{cli.replace('-code', '')}_command") or ("claude" if cli == "claude-code" else "codex"))
        found = shutil.which(command)
        if cli == "codex":
            sdk = importlib.util.find_spec("openai_codex") is not None
            print(f"runs:      {command} ({found or 'NOT FOUND on PATH'}), kept running, through the Codex SDK "
                  f"({'installed' if sdk else 'NOT INSTALLED: pip install openai-codex'})")
        else:
            print(f"runs:      {command} ({found or 'NOT FOUND on PATH'}), headless, once per call")
        print(f"login:     {command}'s own -- a subscription's calls count against its limits")
        if base or key_env:
            print("note:      api_base and key_env are not used by this model")
    else:
        print("api_base:  " + (base or "(the provider's own API)"))
        print("key:       " + (f"${key_env} ({'set' if os.environ.get(key_env) else 'NOT SET'})" if key_env
                               else "the provider's own variable (e.g. GEMINI_API_KEY)"))
    if cfg.get("class"):
        print(f"class:     {cfg['class']}")
    print(f"config:    {h.config_path}")
    for var, what in (("AG_LLM_MODEL", "model"), ("AG_LLM_URL", "api_base"), ("AG_LLM_KEY", "key")):
        if os.environ.get(var):
            print(f"note:      {var} is set and overrides the {what} here")
    model = cfg.get("model") or ""
    if model and "/" not in model and not base:
        print(f"note:      {model!r} names no provider; expected provider/model, e.g. gemini/{model} "
              f"(LiteLLM), or claude-code/{model} or codex/{model} (a CLI, on its login)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ag.ag_harness.home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("path")
    sub.add_parser("list")
    sub.add_parser("gatherers")
    show = sub.add_parser("show")
    show.add_argument("gatherer")
    new = sub.add_parser("new")
    new.add_argument("gatherer")
    new.add_argument("--policy")
    new.add_argument("--poller", action="append", default=[])
    new.add_argument("--no-pollers", action="store_true")
    new.add_argument("--force", action="store_true")
    mod = sub.add_parser("model")
    mod.add_argument("model", nargs="?")
    mod.add_argument("--api-base", help='send every call to this server ("": the provider\'s own API)')
    mod.add_argument("--key-env", help='read the key from this variable ("": the provider\'s own)')
    con = sub.add_parser("contract")
    con.add_argument("--gatherer")
    con.add_argument("--policy")
    con.add_argument("--poller", action="append", default=[])
    con.add_argument("--no-pollers", action="store_true")
    a = ap.parse_args(argv)
    h = home()
    try:
        if a.cmd == "path":
            h.ensure()
            print(h.root)
            return 0
        if a.cmd == "list":
            return cmd_list(h)
        if a.cmd == "gatherers":
            return cmd_gatherers(h)
        if a.cmd == "contract":
            print(json.dumps(contract(h, a.gatherer, a.policy, a.poller, a.no_pollers)))
            return 0
        if a.cmd == "show":
            return cmd_show(h, a.gatherer)
        if a.cmd == "model":
            return cmd_model(h, a.model, a.api_base, a.key_env)
        return cmd_new(h, a.gatherer, a.policy, a.poller, a.force, a.no_pollers)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
