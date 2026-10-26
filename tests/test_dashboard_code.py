"""Code, coloured (ag_dashboard/page.html's "code, coloured" section): the page's own highlighter, its shell reader and
how it lays a command out, and a command's output in its terminal's colours -- run in Node, without the rest of the page."""
import html
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "ag_dashboard", "page.html")
START = "// ------------------------------------------------------------------ code, coloured"
END = "// a code block's Copy"
API = "hlTokens, hlLines, shellHtml, outputHtml, ansiHtml, hlLang, langOfPath, guessWeb"
# the section, given what it uses of the page, its functions called on each case: [name, ...arguments] -> the result
RUN = r"""
const escapeHtml = (t) => t.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const el = () => ({});
%s
const api = { %s };
let input = "";
process.stdin.on("data", (d) => { input += d; }).on("end", () =>
  process.stdout.write(JSON.stringify(JSON.parse(input).map(([f, ...a]) => api[f](...a)))));
"""


def section() -> str:
    with open(PAGE, encoding="utf-8") as fh:
        text = fh.read()
    return text[text.index(START):text.index(END)]


def run(*cases):
    """Each case [function, ...arguments], run in the page's code: the results."""
    got = subprocess.run(["node", "-e", RUN % (section(), API)], input=json.dumps(cases), capture_output=True,
                         text=True, timeout=30)
    if got.returncode:
        raise AssertionError(got.stderr)
    return json.loads(got.stdout)


def plain(markup: str) -> str:
    """HTML as its text: what the reader sees, less the tags."""
    return html.unescape(re.sub(r"<[^>]+>", "", markup.replace("&#8203;", "")))


def laid_out(markup: str):
    """A command as shellHtml lays it out: each line's indent and its text."""
    return [(int(i), plain(t)) for i, t in re.findall(r'<div class="sh-l(?: p)?" style="--i:(\d+)">(.*?)</div>', markup)]


def tokens(pairs):
    """[class, text] tokens as {class: [texts]}, plain text left out."""
    out = {}
    for cls, t in pairs:
        if cls:
            out.setdefault(cls, []).append(t)
    return out


@unittest.skipUnless(shutil.which("node"), "needs Node to run the page's code")
class HighlightTest(unittest.TestCase):

    def test_python_colours_what_a_reader_scans_for(self):
        [toks] = run(["hlTokens", 'import os\n@cache\ndef go(x=1.5):  # why\n    return f"{x}" if x else None', "python"])
        got = tokens(toks)
        self.assertEqual(got["kw"], ["import", "def", "return", "if", "else"])
        self.assertEqual(got["fn"], ["go"])
        self.assertEqual(got["num"], ["1.5", "None"])
        self.assertEqual(got["com"], ["# why"])
        self.assertEqual(got["str"], ['f"{x}"'])
        self.assertEqual(got["meta"], ["@cache"])

    def test_a_string_over_several_lines_is_closed_and_opened_again_on_each(self):
        [lines] = run(["hlLines", 'x = """a\nb"""', "python"])
        self.assertEqual(lines, ['x = <span class="hl-str">&quot;&quot;&quot;a</span>', '<span class="hl-str">b&quot;&quot;&quot;</span>'])

    def test_languages_by_name_and_by_a_files_extension(self):
        got = run(["hlLang", "Python"], ["hlLang", "tsx"], ["hlLang", "zsh"], ["hlLang", "made-up"],
                  ["langOfPath", "a/b.toml"], ["langOfPath", "~/.zshrc"], ["langOfPath", "Makefile"])
        self.assertEqual(got, ["python", "js", "shell", None, "toml", "shell", None])

    def test_a_piece_of_a_web_page_is_read_as_its_markup_style_or_script(self):
        got = run(["guessWeb", "const a = 1;\nfunction f() {\n}"], ["guessWeb", ".a { color: red; }\n.b {\n  margin: 0;\n}"],
                  ["guessWeb", '<div class="x">\n</div>'])
        self.assertEqual(got, ["js", "css", "html"])

    def test_every_language_keeps_the_text_as_written(self):
        with open(os.path.join(ROOT, "ag_dashboard", "files.py"), encoding="utf-8") as fh:
            py = fh.read()
        page = section()
        cases = [["hlLines", py, "python"], ["hlLines", page, "js"], ["hlLines", page, "html"], ["hlLines", page, "css"],
                 ["hlLines", '{"a": [1, "b\\"c"]}', "json"], ["hlLines", "[x]\na = 'b' # c", "toml"],
                 ["hlLines", "a: [1, 'b'] # c\n- k: v", "yaml"], ["hlLines", "SELECT 'it''s' -- c", "sql"],
                 ["hlLines", "fn main() { let s = \"x\"; } // c", "clike"], ["hlLines", "# h\n- `a` **b**", "md"],
                 ["hlLines", "@@ -1 +1 @@\n-a\n+b", "diff"], ["hlLines", "$ ls -la\ntotal 0", "console"]]
        for (_, text, lang), lines in zip(cases, run(*cases)):
            self.assertEqual(plain("\n".join(lines)), text, lang)


@unittest.skipUnless(shutil.which("node"), "needs Node to run the page's code")
class ShellTest(unittest.TestCase):

    def test_the_command_run_its_flags_variables_and_operators(self):
        [toks] = run(["hlTokens", 'FOO=1 env -u X sudo -E python3 -m x "$HOME/a $(date)" 2>&1 | tail -5 # c', "shell"])
        got = tokens(toks)
        self.assertEqual(got["cmd"], ["env", "sudo", "python3", "date", "tail"])   # past a wrapper and its flags' words
        self.assertEqual(got["flag"], ["-u", "-E", "-m", "-5"])
        self.assertEqual(got["var"], ["FOO", "$HOME"])
        self.assertEqual(got["op"], ["$(", ")", "2>&1", "|"])
        self.assertEqual(got["com"], ["# c"])

    def test_a_heredocs_body_is_coloured_as_what_reads_it(self):
        [toks] = run(["hlTokens", "python3 - <<'EOF'\nimport os\nEOF\ncat > a.json <<EOF\n{\"a\": 1}\nEOF", "shell"])
        got = tokens(toks)
        self.assertIn("import", got["kw"])               # python reads the first
        self.assertEqual(got["prop"], ['"a"'])            # the second is written to a .json
        self.assertEqual(got["op"], ["<<'EOF'", "EOF", ">", "<<EOF", "EOF"])

    def test_a_long_command_is_broken_after_its_steps_and_its_pipes_indented_under_them(self):
        [markup] = run(["shellHtml", "cd /Users/sep/x && git diff a b -- one.py two.py three.py | grep -E '^[+-]' | head -60; git status",
                      "/Users/sep"])
        self.assertEqual(laid_out(markup), [(0, "$ cd ~/x &&"), (1, "git diff a b -- one.py two.py three.py | grep -E '^[+-]' | head -60"),
                                 (0, "git status")])

    def test_a_short_command_stays_on_its_line_and_loops_are_indented(self):
        short, loop = run(["shellHtml", "ls -la && pwd", ""],
                          ["shellHtml", "for f in *.py; do echo \"$f\"; wc -l \"$f\" | sort -rn | head -3; done; echo all files counted", ""])
        self.assertEqual(short.count('class="sh-l'), 1)
        self.assertEqual(laid_out(loop),
                         [(0, "$ for f in *.py; do"), (1, 'echo "$f"'), (1, 'wc -l "$f" | sort -rn | head -3'), (0, "done"),
                          (0, "echo all files counted")])

    def test_what_cannot_be_read_is_still_shown_whole(self):
        for text in ['echo "never closed && more', "ls (unbalanced", "cat <<EOF\nno end", "a | | b; ;"]:
            [lines] = run(["hlLines", text, "shell"])
            self.assertEqual(plain("\n".join(lines)), text)


@unittest.skipUnless(shutil.which("node"), "needs Node to run the page's code")
class OutputTest(unittest.TestCase):

    def test_a_terminals_colours_are_kept_and_its_other_escapes_dropped(self):
        [markup] = run(["ansiHtml", "\x1b[1;31mFAIL\x1b[0m ok \x1b[32mpass\x1b[39m\x1b]0;title\x07\n10%\r100%"])
        self.assertEqual(markup, '<span class="a-red a-bold">FAIL</span> ok <span class="a-green">pass</span>\n100%')

    def test_output_with_no_colours_is_coloured_as_what_it_plainly_is(self):
        diff, js, text = run(["outputHtml", "-a\n+b\n@@ -1 +1 @@", "git diff x | head"], ["outputHtml", '{"a": 1}', "curl x"],
                             ["outputHtml", "-a\n+b", "cat notes"])
        self.assertIn('<span class="hl-del">-a</span>', diff)
        self.assertIn('<span class="hl-prop">&quot;a&quot;</span>', js)
        self.assertEqual(text, "-a\n+b")                  # not from a diff: as printed


if __name__ == "__main__":
    unittest.main()
