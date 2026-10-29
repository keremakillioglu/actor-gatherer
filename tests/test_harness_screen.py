"""A terminal's screen read back (harness_kit/screen.py), and each harness's rule for what has the keys on it
(`Harness.box`): its message box, empty or holding something, or a dialog. The screens are drawn as Claude Code
2.1.312 and codex 0.164.0 draw theirs (recorded in a pseudo-terminal), cut down to the rows the rules read."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness_kit  # noqa: E402
from harness_kit.base import Box  # noqa: E402
from harness_kit.screen import Screen  # noqa: E402

COLS, ROWS = 80, 14
RULE = "─" * COLS
FAINT = "\x1b[2m{}\x1b[22m"


def drawn(rows, cursor, shown=True):
    """A full screen: each of `rows` ({row: text}) drawn at its row, then the cursor put at `cursor` (row, column),
    shown or hidden -- as both harnesses draw: from a cleared alternate screen, by position."""
    out = "\x1b[?1049h\x1b[?25l\x1b[2J"
    for r, text in sorted(rows.items()):
        out += f"\x1b[{r + 1};1H{text}"
    out += f"\x1b[{cursor[0] + 1};{cursor[1] + 1}H" + ("\x1b[?25h" if shown else "")
    s = Screen(COLS, ROWS)
    s.feed(out.encode())
    return s


class ScreenTest(unittest.TestCase):
    def test_text_where_the_cursor_puts_it(self):
        s = Screen(20, 4)
        s.feed(b"hello\r\nworld\x1b[1;3HY\x1b[2;1H\x1b[2K\x1b[4;18Hend")
        self.assertEqual(s.lines(), ["heYlo", "", "", "                 end"])
        self.assertEqual((s.y, s.x), (3, 19))

    def test_pieces_cut_in_an_escape_or_a_character_are_joined(self):
        s = Screen(20, 2)
        data = "a\x1b]0;a title\x1b\\\x1b[2;5Hé❯".encode()
        for i in range(len(data)):
            s.feed(data[i:i + 1])
        self.assertEqual(s.lines(), ["a", "    é❯"])

    def test_a_long_line_wraps_and_the_last_row_scrolls(self):
        s = Screen(4, 2)
        s.feed(b"abcdefgh\r\nij")
        self.assertEqual(s.lines(), ["efgh", "ij"])

    def test_a_wide_character_takes_two_columns(self):
        s = Screen(6, 1)
        s.feed("界x".encode())
        self.assertEqual(s.cells(0)[1][0], "")
        self.assertEqual(s.lines(), ["界x"])
        self.assertEqual(s.x, 3)

    def test_the_alternate_screen_comes_and_goes_with_the_main_one_kept(self):
        s = Screen(10, 2)
        s.feed(b"shell$\x1b[?1049h\x1b[2Jfull\x1b[?1049l")
        self.assertEqual(s.lines(), ["shell$", ""])
        self.assertEqual((s.y, s.x), (0, 6))

    def test_a_scroll_region_and_lines_put_in_and_taken_out(self):
        s = Screen(5, 4)
        s.feed(b"1\r\n2\r\n3\r\n4\x1b[2;3r\x1b[3;1H\r\nx\x1b[r\x1b[1;1H\x1b[1L")
        self.assertEqual(s.lines(), ["", "1", "3", "x"])
        s.feed(b"\x1b[1M")
        self.assertEqual(s.lines(), ["1", "3", "x", ""])

    def test_styles_kept_per_character(self):
        s = Screen(10, 1)
        s.feed(b"\x1b[1ma\x1b[2mb\x1b[0;38;5;245mc\x1b[mx")
        styles = [st for _, st in s.cells(0)[:4]]
        self.assertTrue(styles[0].bold and not styles[0].faint)
        self.assertTrue(styles[1].faint)
        self.assertEqual((styles[2].fg, styles[2].bold), ("5;245", False))
        self.assertEqual(styles[3].fg, None)

    def test_the_cursor_shown_or_hidden(self):
        s = Screen(10, 2)
        self.assertTrue(s.cursor_shown)
        s.feed(b"\x1b[?25l")
        self.assertFalse(s.cursor_shown)

    def test_made_smaller_it_keeps_the_cursor_s_row(self):
        s = Screen(10, 4)
        s.feed(b"a\r\nb\r\nc\r\nd")
        s.resize(8, 2)
        self.assertEqual((s.lines(), s.y), (["c", "d"], 1))


class ClaudeBoxTest(unittest.TestCase):
    h = harness_kit.get("claude")

    def box(self, prompt, cursor, shown=True, top=RULE, extra=None):
        rows = {8: top, 9: prompt, 10: RULE, 11: "  ⏵⏵ auto mode on (shift+tab to cycle)"}
        return self.h.box(drawn({**rows, **(extra or {})}, cursor, shown))

    def test_its_box_empty_with_its_placeholder(self):
        self.assertEqual(self.box("❯ " + FAINT.format('Try "fix lint errors"'), (9, 2)), Box.EMPTY)
        self.assertEqual(self.box("❯", (9, 2)), Box.EMPTY)
        self.assertEqual(self.box("❯ ", (9, 2), top="─── History 9/9 " + "─" * 60), Box.EMPTY)   # a labelled rule

    def test_its_box_holding_what_was_typed(self):
        self.assertEqual(self.box("❯ hello there", (9, 13)), Box.HOLDS)
        self.assertEqual(self.box("❯ /mc", (9, 5), extra={6: "  ❯ /mcp      Manage MCP servers"}), Box.HOLDS)
        self.assertEqual(self.box("\x1b[38;2;253;93;177m!\x1b[39m", (9, 2)), Box.HOLDS)     # its shell mode
        two = {8: RULE, 9: "❯ first", 10: "  second", 11: RULE, 12: "  ⏸ manual mode on"}
        self.assertEqual(self.h.box(drawn(two, (10, 8))), Box.HOLDS)

    def test_a_dialog_a_question_or_a_permission_has_the_keys(self):
        mcp = {3: "▔" * COLS, 4: "   Manage MCP servers", 6: "   ❯ ✔ claude.ai Claude Docs     8 tools",
               13: "   ↑/↓ to navigate · Enter to confirm · Esc to cancel"}
        self.assertEqual(self.h.box(drawn(mcp, (6, 3), shown=False)), Box.AWAY)
        permission = {2: RULE, 3: " Create file", 6: " Do you want to create a.txt?", 7: " ❯ 1. Yes", 8: "   3. No",
                      10: " Esc to cancel · Tab to amend"}
        self.assertEqual(self.h.box(drawn(permission, (7, 1), shown=False)), Box.AWAY)
        question = {3: "❯ Use the AskUserQuestion tool", 4: RULE, 5: " ☐ Drink", 7: "Tea or coffee?",
                    9: "❯ 1. Tea", 11: "  3. Type something.", 12: RULE, 13: "Enter to select · Esc to cancel"}
        self.assertEqual(self.h.box(drawn(question, (11, 20), shown=True)), Box.AWAY)   # even with its cursor shown
        self.assertEqual(self.box("❯ " + FAINT.format("Try"), (9, 2), shown=False), Box.AWAY)

    def test_its_cursor_shown_away_from_any_box(self):
        self.assertEqual(self.h.box(drawn({0: "Welcome to Claude Code", 1: "Loading…"}, (1, 8))), Box.AWAY)


class CodexBoxTest(unittest.TestCase):
    h = harness_kit.get("codex")

    def screen(self, composer, cursor, shown=True, more=None):
        rows = {2: "› an earlier message", 4: "• ok", 8: composer, 10: "  GPT-6-Luna low · /work", 11: "  ? for shortcuts"}
        return drawn({**rows, **(more or {})}, cursor, shown)

    def test_its_composer_empty_with_its_placeholder(self):
        bold = "\x1b[1m›\x1b[22m "
        self.assertEqual(self.h.box(self.screen(bold + FAINT.format("Ask Codex to do anything"), (8, 2))), Box.EMPTY)

    def test_its_composer_holding_what_was_typed(self):
        self.assertEqual(self.h.box(self.screen("› hello there", (8, 13))), Box.HOLDS)
        self.assertEqual(self.h.box(self.screen("› first line", (9, 8), more={9: "  second"})), Box.HOLDS)
        self.assertEqual(self.h.box(self.screen("› " + FAINT.format("Ask"), (8, 2), more={9: "  below the cursor"})),
                         Box.HOLDS)                                             # what is typed goes on below it

    def test_a_popup_or_an_approval_has_the_keys(self):
        model = {6: "  Select Model and Effort", 9: "› 1. GPT-6-Luna (current)  Fast", 10: "  2. GPT-5.6-Terra",
                 13: "  enter select · esc back"}
        self.assertEqual(self.h.box(drawn(model, (13, 79), shown=False)), Box.AWAY)
        approval = {5: "  Would you like to run the following command?", 7: "  $ touch a.txt",
                    10: "› 1. Yes, proceed (y)", 11: "  3. No, and tell Codex what to do differently (esc)",
                    13: "  Press enter to confirm or esc to cancel"}
        self.assertEqual(self.h.box(drawn(approval, (13, 79), shown=False)), Box.AWAY)

    def test_its_cursor_shown_away_from_its_composer(self):
        self.assertEqual(self.h.box(self.screen("› " + FAINT.format("Ask"), (4, 3))), Box.AWAY)     # on its reply
        self.assertEqual(self.h.box(drawn({0: "  Update available", 2: "› 1. Update now", 3: "  2. Skip",
                                           13: "  enter continue · esc skip"}, (2, 2))), Box.AWAY)   # too far up


class NoRuleTest(unittest.TestCase):
    def test_a_harness_with_no_rule_does_not_say(self):
        class Other(harness_kit.Harness):
            def items(self, history):
                return []

            def read(self, items):
                return []
        self.assertIsNone(Other().box(drawn({0: "anything"}, (0, 0))))


if __name__ == "__main__":
    unittest.main()
