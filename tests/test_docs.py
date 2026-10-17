"""The docstrings the docs page is made from (docs/docs.md's `<!-- gen: doc ... -->` markers)
render as written: every line after the summary is indented at least as much as the
docstring itself. One line short of it leaves the others indented, and Markdown shows them
as a code block."""

import ast
import importlib.util
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class DocsDocstrings(unittest.TestCase):
    def test_every_docstring_the_docs_show_is_evenly_indented(self):
        markers = re.findall(r"<!-- gen: doc (\S+)", open(os.path.join(ROOT, "docs", "docs.md"), encoding="utf-8").read())
        self.assertTrue(markers)
        for target in set(markers):
            module, _, cls = target.partition(":")
            node = ast.parse(open(importlib.util.find_spec(module).origin, encoding="utf-8").read())
            if cls:
                node = next(n for n in node.body if isinstance(n, ast.ClassDef) and n.name == cls)
            expr = node.body[0]
            lines = [line for line in expr.value.value.split("\n")[1:] if line.strip()]
            short = [line for line in lines if len(line) - len(line.lstrip()) < expr.col_offset]
            self.assertEqual(short, [], target)


if __name__ == "__main__":
    unittest.main()
