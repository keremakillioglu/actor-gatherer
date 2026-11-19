"""The dashboard's page as one text, as page.html held it before it was split into frontend/ (ag_dashboard/DESIGN.md,
steps A3 and after): its markup (frontend/index.html), its styles (those src/styles.ts imports, in order) and its
script (src/page.js's modules in core/page/ and features/: each one page.js imports, then each of theirs, in import
order). For the tests that read the page, or run a part of its script in Node."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONT = os.path.join(ROOT, "frontend")
SRC = os.path.join(FRONT, "src")
MODULE = '<script type="module" src="/src/main.ts"></script>'
# an import of a module of the script or a stylesheet: `import "./x.js";` or `... from "../y/z.js";`
IMPORT = re.compile(r"""(?:^import\s+|\bfrom\s+)["'](\.{1,2}/[^"']+\.(?:js|css))["']""", re.M)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _imports(path: str) -> list:
    return [os.path.normpath(os.path.join(os.path.dirname(path), m)) for m in IMPORT.findall(_read(path))]


def script_files() -> list:
    """The paths of the script's modules: page.js's, then each one's own, depth first, each once."""
    seen, out = set(), []

    def visit(path):
        for p in _imports(path):
            if p.endswith(".js") and p not in seen:
                seen.add(p)
                out.append(p)
                visit(p)
    visit(os.path.join(SRC, "page.js"))
    return out


def script() -> str:
    return "".join(_read(p) for p in script_files())


def styles() -> str:
    return "".join(_read(p) for p in _imports(os.path.join(SRC, "styles.ts")))


def text() -> str:
    """The whole page: its styles in its head, its script where the module's tag is."""
    head, rest = _read(os.path.join(FRONT, "index.html")).split("</head>", 1)
    return head + "<style>\n" + styles() + "</style>\n</head>" + rest.replace(MODULE, "<script>\n" + script() + "</script>", 1)
