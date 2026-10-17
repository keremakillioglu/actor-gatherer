"""The docs page's build steps, run by mkdocs (mkdocs.yml `hooks`).

- `<!-- gen: stub module:Class member ... -->` in docs.md becomes a code block listing those
  members of the class as the source declares them: attributes with their annotation,
  methods with their signature, each with the first sentence of its documentation.
- `<!-- gen: harness NAME -->` becomes NAME's entry in ag/cli/harnesses.toml.
- `<!-- gen: config TABLE -->` becomes that part of the config.toml ag writes on first run
  (ag.ag_harness.home.TEMPLATE, and ag.cli.config.HEADER for [cli]): policies, policies.llm,
  pollers or cli.
- `<!-- gen: readme SECTION -->` becomes the body of the README's `## SECTION`, its own
  headings one level down and its links to the rest of the README pointed at GitHub.
- `<!-- gen: doc module[:Class] [TITLE] -->` becomes that docstring, as Markdown: the part
  before its first titled section, less its summary line (which is for readers of the
  code), or the section titled TITLE (a title is a line underlined with dashes).
- `<!-- gen: options -->`, `commands`, `env general|harness`, `llm-settings`, `home-layout`
  and `harness-keys` become tables or blocks made from the data the code keeps: ag.cli.usage,
  ag.cli.config.ENVIRONMENT, each launcher's `environment`, ag.ag_harness.home (LLM_SETTINGS, LAYOUT) and
  ag/cli/harnesses.toml.
- Tables are wrapped for horizontal scrolling, and the sidebar is made from the page's
  h2 and h3 headings.
"""

import ast
import importlib.util
import inspect
import os
import re
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = re.compile(r"<!-- gen: ([\w-]+)(?: (.*?))? -->")


def first_sentence(text: str) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.+?(?<!\be\.g)(?<!\bi\.e)\.)(\s|$)", text)
    return (m.group(1) if m else text).rstrip(".")


def comment_above(lines, lineno: int) -> str:
    """The `#:` comment right above line `lineno` (1-based), joined."""
    out, i = [], lineno - 2
    while i >= 0 and lines[i].strip().startswith("#:"):
        out.insert(0, lines[i].strip()[2:].strip())
        i -= 1
    return " ".join(out)


def stub(spec: str, members) -> str:
    module, _, cls_name = spec.partition(":")
    path = importlib.util.find_spec(module).origin
    source = open(path, encoding="utf-8").read()
    lines = source.splitlines()
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    found = {}
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found[node.target.id] = (f"{node.target.id}: {ast.unparse(node.annotation)}",
                                     comment_above(lines, node.lineno), [])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = ast.unparse(node.args)
            ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]
            found[node.name] = (f"def {node.name}({sig}){ret}: ...", ast.get_docstring(node) or "", decorators)
    bases = ", ".join(ast.unparse(b) for b in cls.bases)
    out = [f"class {cls_name}({bases}):"]
    for name in members:
        if name not in found:
            raise ValueError(f"{spec} has no member {name}")
        decl, doc, decorators = found[name]
        if doc:
            out += ["    # " + l for l in textwrap.wrap(first_sentence(doc), 88)]
        out += [f"    {d}" for d in decorators] + [f"    {decl}"]
    return "\n".join(out)


def harness(name: str) -> str:
    text = open(os.path.join(ROOT, "ag", "cli", "harnesses.toml"), encoding="utf-8").read()
    m = re.search(rf"^\[cli\.harnesses\.{re.escape(name)}\]\n(?:(?!\n\[).)*", text, re.S | re.M)
    if not m:
        raise ValueError(f"no [cli.harnesses.{name}] in ag/cli/harnesses.toml")
    return m.group(0).rstrip()


def config(table: str) -> str:
    """A part of the config.toml ag writes, as blank-line separated blocks (a table with the
    comment above it): policies (the defaults and the catalog), policies.llm, pollers, cli."""
    from ag.ag_harness.home import TEMPLATE
    from ag.cli.config import HEADER
    blocks = [b.strip("\n") for b in (TEMPLATE + HEADER).split("\n\n") if b.strip()]

    def at(header: str) -> int:
        return next(i for i, b in enumerate(blocks) if re.search(rf"^{re.escape(header)}$", b, re.M))

    def rule(name: str) -> int:
        return next(i for i, b in enumerate(blocks) if b.startswith("# ----") and name in b.splitlines()[0])

    divider = re.compile(r"^# ====")
    if table == "policies":
        catalog = blocks[rule("available policies"):]
        catalog = catalog[:next(i for i, b in enumerate(catalog) if divider.match(b))]
        return "\n\n".join([blocks[at("[policies]")]] + catalog)
    if table == "policies.llm":
        return blocks[at("[policies.llm]")]
    if table == "pollers":
        rest = blocks[at("[pollers]"):]
        return "\n\n".join(rest[:next((i for i, b in enumerate(rest) if divider.match(b)), len(rest))])
    if table == "cli":
        return blocks[at("[cli]")]
    raise ValueError(f"no config table {table!r}")


README_URL = "https://github.com/ucbepic/actor-gatherer"


def readme(section: str) -> str:
    text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    m = re.search(rf"^## {re.escape(section)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        raise ValueError(f"README.md has no section ## {section}")
    body = m.group(1).strip()
    body = re.sub(r"^(#{3,5}) ", lambda h: "#" * len(h.group(1)) + " ", body, flags=re.M)
    own = {re.sub(r"[^\w\s-]", "", h.lower()).strip().replace(" ", "-")
           for h in re.findall(r"^#{3,5} (.+)$", body, re.M)}
    return re.sub(r"\]\(#([\w-]+)\)",
                  lambda l: l.group(0) if l.group(1) in own else f"]({README_URL}#{l.group(1)})", body)


def docstring(target: str, title: str = "") -> str:
    module, _, cls = target.partition(":")
    source = open(importlib.util.find_spec(module).origin, encoding="utf-8").read()
    node = ast.parse(source)
    if cls:
        node = next(n for n in node.body if isinstance(n, ast.ClassDef) and n.name == cls)
    doc = ast.get_docstring(node) or ""
    parts = re.split(r"^(.+)\n-{3,}$", doc, flags=re.M)        # [intro, title, body, title, body, ...]
    if not title:
        intro = parts[0].strip().split("\n\n", 1)              # the summary line is for readers of the code
        return intro[1].strip() if len(intro) > 1 else ""
    sections = dict(zip(parts[1::2], parts[2::2]))
    if title not in sections:
        raise ValueError(f"{target} has no section {title!r}: {list(sections)}")
    return sections[title].strip()


def cell(text: str) -> str:
    return text.replace("|", "&#124;") if "`" not in text else re.sub(
        r"`([^`]*\|[^`]*)`", lambda m: "<code>" + m.group(1).replace("<", "&lt;").replace(">", "&gt;")
        .replace("|", "&#124;") + "</code>", text)


def table(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(out + ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows])


def options() -> str:
    from ag.cli.usage import OPTIONS
    return table(("flag", "meaning"), [(f"`{o}`", d) for o, d in OPTIONS if not o.startswith("-h")])


def commands() -> str:
    from ag.cli.usage import COMMANDS
    return table(("command", "does"), [(" / ".join(f"`{c.strip()}`" for c in cmd.split(" / ")), d)
                                      for cmd, d in COMMANDS])


def harness_environment():
    """(harness, name, default, meaning) for each variable a shipped harness's launcher declares."""
    import tomllib
    from ag.cli.launch import load_launcher
    entries = tomllib.load(open(os.path.join(ROOT, "ag", "cli", "harnesses.toml"), "rb"))["cli"]["harnesses"]
    return [(h, *v) for h, e in entries.items() for v in load_launcher(e["launcher"]).environment]


def environment(scope: str) -> str:
    from ag.cli.config import ENVIRONMENT
    if scope == "harness":
        return table(("variable", "harness", "default", "meaning"),
                     [(f"`{n}`", h, f"`{d}`", m) for h, n, d, m in harness_environment()])
    return table(("variable", "default", "meaning"),
                 [(f"`{n}`", f"`{d}`" if d.startswith(("~", "python", "[")) else d or "none", m)
                  for n, h, d, m in ENVIRONMENT if not h])


def llm_settings() -> str:
    from ag.ag_harness.home import LLM_SETTINGS
    return table(("key", "for", "default", "meaning", "overridden by"),
                 [(f"`{k}`", f, f"`{d}`" if d not in ("none",) and not d.startswith("the ") else d, m,
                   (f"`{o.split(' ')[0]}`" + o[len(o.split(' ')[0]):]) if o else "")
                  for k, f, d, m, o in LLM_SETTINGS])


def harness_keys() -> str:
    """Every key of ag/cli/harnesses.toml's entries: the harnesses that have it, its value
    in each, and the comment that says what it is."""
    import tomllib
    path = os.path.join(ROOT, "ag", "cli", "harnesses.toml")
    text = open(path, encoding="utf-8").read()
    entries = tomllib.loads(text)["cli"]["harnesses"]
    meaning = {}
    for key, comment in re.findall(r"^(\w+)\s*=.*?#\s*(.+)$", text, re.M):
        meaning.setdefault(key, comment.strip())
    rows = []
    for key in dict.fromkeys(k for entry in entries.values() for k in entry):
        have = [h for h, e in entries.items() if key in e]
        values = {h: entries[h][key] for h in have}
        shown = {h: f"`{v!r}`".replace("'", '"') for h, v in values.items()}
        if len(set(shown.values())) == 1:
            default = next(iter(shown.values()))
        elif key in ("launcher", "adaptor", "command"):
            default = "each harness's own"
        else:
            default = " / ".join(f"{v} ({h})" for h, v in shown.items())
        rows.append((f"`{key}`", "all" if len(have) == len(entries) else ", ".join(have), default,
                     meaning.get(key, "")))
    return table(("key", "harnesses", "default", "meaning"), rows)


def generate(kind: str, args: str) -> str:
    words = args.split()
    if kind == "readme":
        return readme(args.strip())
    if kind == "doc":
        return docstring(words[0], " ".join(words[1:]))
    if kind == "options":
        return options()
    if kind == "commands":
        return commands()
    if kind == "env":
        return environment(words[0])
    if kind == "llm-settings":
        return llm_settings()
    if kind == "harness-keys":
        return harness_keys()
    if kind == "home-layout":
        from ag.ag_harness.home import LAYOUT
        return f"```text\n{LAYOUT}\n```"
    if kind == "stub":
        code = stub(words[0], words[1:])
    elif kind == "harness":
        code = harness(words[0])
    elif kind == "config":
        code = config(words[0])
    else:
        raise ValueError(f"unknown generator {kind!r}")
    lang = {"stub": "python", "harness": "toml", "config": "toml"}[kind]
    return f"```{lang}\n{code}\n```"


def on_config(config):
    sys.path.insert(0, ROOT)                 # the source the generators read: this clone's ag
    return config


def on_page_markdown(markdown, page, config, files):
    return GEN.sub(lambda m: generate(m.group(1), m.group(2) or ""), markdown)


def on_page_content(html, page, config, files):
    html = html.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    sidebar = []
    for level, hid, title in re.findall(r'<h([23]) id="([^"]+)">(.*?)</h\1>', html, re.S):
        if level == "2":
            sidebar.append({"id": hid, "title": title, "children": []})
        elif sidebar:
            sidebar[-1]["children"].append({"id": hid, "title": title})
    page.sidebar = sidebar
    return html
