"""The docs page's build steps, run by mkdocs (mkdocs.yml `hooks`).

- `<!-- gen: stub module:Class member ... -->` in docs.md becomes a code block listing those
  members of the class as the source declares them: attributes with their annotation,
  methods with their signature, each with the first sentence of its documentation.
- `<!-- gen: harness NAME -->` becomes NAME's entry in ag/cli/harnesses.toml.
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
GEN = re.compile(r"<!-- gen: (\w+) (.*?) -->")


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


def generate(kind: str, args: str) -> str:
    words = args.split()
    if kind == "stub":
        code = stub(words[0], words[1:])
    elif kind == "harness":
        code = harness(words[0])
    else:
        raise ValueError(f"unknown generator {kind!r}")
    return f"```\n{code}\n```"


def on_config(config):
    sys.path.insert(0, ROOT)                 # the source the generators read: this clone's ag
    return config


def on_page_markdown(markdown, page, config, files):
    return GEN.sub(lambda m: generate(m.group(1), m.group(2)), markdown)


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
