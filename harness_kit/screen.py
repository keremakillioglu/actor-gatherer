"""A terminal's screen as what a program printed to it leaves it: rows of characters, each with its style. Enough of
a terminal (xterm's) to read a harness's own screen back -- cursor moves, erasing, scroll regions, the alternate
screen of a full-screen program, wide characters -- not to draw one: no scrollback, no charsets, no mouse.
Standard library only.

    screen = Screen(cols, rows)
    screen.feed(chunk)                   # bytes as the program printed them, in pieces as they came
    screen.lines()                       # each row's text
    screen.cells(row)                    # [(character, Style), ...] -- a wide character's second column ""
"""

import codecs
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class Style:
    """A character's look, as the program set it (SGR): `fg`, its colour as the program named it -- "1" (red, of the
    8), "9" (bright red), "5;245" (of the 256), "2;r;g;b"; None the terminal's own."""
    bold: bool = False
    faint: bool = False
    italic: bool = False
    inverse: bool = False
    fg: Optional[str] = None
    bg: Optional[str] = None


PLAIN = Style()

#: An escape sequence, whole: CSI (prefix, parameters, intermediates, final), OSC (to BEL or ST), DCS/SOS/PM/APC (to
#: ST), or a short one (ESC and one or two characters) -- never one of those openings alone, cut off where a piece ended.
_ESCAPE = re.compile(r"\x1b(?:\[(?P<pre>[?>=<!]?)(?P<args>[0-9;:]*)(?P<mid>[ -/]*)(?P<fin>[@-~])"
                     r"|\](?P<osc>[^\x07\x1b]*)(?:\x07|\x1b\\)|[P^_X][^\x1b]*\x1b\\|(?P<short>[ -/]*[0-OQ-WYZ\\`-~]))", re.S)
#: The start of one, not ended yet: the rest of it comes with the next piece.
_UNENDED = re.compile(r"\x1b(?:\[[?>=<!]?[0-9;:]*[ -/]*|\][^\x07\x1b]*\x1b?|[P^_X][^\x1b]*\x1b?|[ -/]*)", re.S)
_TEXT = re.compile(r"[^\x00-\x1f\x7f\x1b]+")
HOLD_MAX = 65536                         # an escape sequence not ended after this many characters: not one


def width(ch: str) -> int:
    """Columns `ch` takes: 2 wide (East Asian wide or full-width), 0 a combining mark or a zero-width one, else 1."""
    if ch < "̀":
        return 1
    if unicodedata.combining(ch) or ch in "​‌‍⁠﻿" or "︀" <= ch <= "️":
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


class Screen:
    def __init__(self, cols: int = 80, rows: int = 24):
        self.cols, self.rows = max(1, cols), max(1, rows)
        self._decode = codecs.getincrementaldecoder("utf-8")("replace")
        self._held = ""                  # the start of an escape sequence the next piece ends
        self.reset()

    def reset(self) -> None:
        self.main = self._blank_buffer()
        self.alt = self._blank_buffer()
        self.buffer = self.main          # the one shown: the alternate screen while a full-screen program has it
        self.x = self.y = 0
        self.wrap = False                # the cursor past the last column: the next character starts a new row
        self.autowrap = True
        self.cursor_shown = True         # the cursor shown (DECTCEM): a program hides it while it draws, and where it
                                         # has no place to type in
        self.top, self.bottom = 0, self.rows - 1
        self.style = PLAIN
        self.saved: Tuple[int, int, Style] = (0, 0, PLAIN)
        self.last = " "                  # the last character drawn (REP repeats it)

    # ---- reading it

    def lines(self) -> List[str]:
        """Each row's text, its trailing blanks taken off."""
        return ["".join(ch for ch, _ in row).rstrip() for row in self.buffer]

    def cells(self, row: int) -> List[Tuple[str, Style]]:
        return list(self.buffer[row])

    def text(self) -> str:
        return "\n".join(self.lines()).rstrip("\n")

    # ---- what the program prints

    def feed(self, data: bytes) -> None:
        s = self._held + self._decode.decode(data)
        self._held = ""
        i, n = 0, len(s)
        while i < n:
            c = s[i]
            if c == "\x1b":
                m = _ESCAPE.match(s, i)
                if m is None:
                    if n - i < HOLD_MAX and _UNENDED.fullmatch(s, i):
                        self._held = s[i:]       # cut off where the piece ended: the next one ends it
                        return
                    i += 1                       # not a sequence: dropped
                    continue
                self._escape(m)
                i = m.end()
            elif c < " " or c == "\x7f":
                self._control(c)
                i += 1
            else:
                m = _TEXT.match(s, i)
                self._print(m.group())
                i = m.end()

    def resize(self, cols: int, rows: int) -> None:
        """The terminal made `cols` x `rows`: rows kept from the top, the cursor's row kept on the screen."""
        cols, rows = max(1, cols), max(1, rows)
        for name in ("main", "alt"):
            buf = getattr(self, name)
            if self.buffer is buf and self.y >= rows:
                del buf[:self.y - rows + 1]
                self.y = rows - 1
            buf = [r[:cols] + [(" ", PLAIN)] * (cols - len(r)) for r in buf[:rows]]
            buf += [self._blank_row(cols) for _ in range(rows - len(buf))]
            if self.buffer is getattr(self, name):
                self.buffer = buf
            setattr(self, name, buf)
        self.cols, self.rows = cols, rows
        self.top, self.bottom = 0, rows - 1
        self.x, self.y, self.wrap = min(self.x, cols - 1), min(self.y, rows - 1), False

    # ---- its parts

    def _blank_row(self, cols: Optional[int] = None) -> list:
        return [(" ", PLAIN)] * (cols or self.cols)

    def _blank_buffer(self) -> list:
        return [self._blank_row() for _ in range(self.rows)]

    def _print(self, run: str) -> None:
        for ch in run:
            w = width(ch)
            if w == 0:
                continue
            if self.wrap:
                if self.autowrap:
                    self.x = 0
                    self._linefeed()
                self.wrap = False
            if self.x + w > self.cols:
                if not self.autowrap:
                    continue
                self.x = 0
                self._linefeed()
            row = self.buffer[self.y]
            if row[self.x][0] == "" and self.x:          # half of a wide one written over: the other half blanked
                row[self.x - 1] = (" ", row[self.x - 1][1])
            row[self.x] = (ch, self.style)
            if w == 2:
                row[self.x + 1] = ("", self.style)
            self.last = ch
            self.x += w
            if self.x >= self.cols:
                self.x, self.wrap = self.cols - 1, True

    def _control(self, c: str) -> None:
        if c == "\r":
            self.x, self.wrap = 0, False
        elif c in "\n\x0b\x0c":
            self._linefeed()
            self.wrap = False
        elif c == "\b":
            self.x, self.wrap = max(0, self.x - 1), False
        elif c == "\t":
            self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)

    def _linefeed(self) -> None:
        if self.y == self.bottom:
            self._scroll_up(1)
        elif self.y < self.rows - 1:
            self.y += 1

    def _scroll_up(self, n: int, top: Optional[int] = None) -> None:
        top = self.top if top is None else top
        n = min(n, self.bottom - top + 1)
        del self.buffer[top:top + n]
        for _ in range(n):
            self.buffer.insert(self.bottom - n + 1, self._blank_row())

    def _scroll_down(self, n: int, top: Optional[int] = None) -> None:
        top = self.top if top is None else top
        n = min(n, self.bottom - top + 1)
        del self.buffer[self.bottom - n + 1:self.bottom + 1]
        for _ in range(n):
            self.buffer.insert(top, self._blank_row())

    def _erase(self, row: int, start: int, end: int) -> None:
        r = self.buffer[row]
        blank = (" ", Style(bg=self.style.bg)) if self.style.bg else (" ", PLAIN)
        for i in range(max(0, start), min(self.cols, end)):
            r[i] = blank

    def _escape(self, m: "re.Match") -> None:
        fin = m.group("fin")
        if fin is not None:
            self._csi(m.group("pre"), m.group("args"), m.group("mid"), fin)
        elif m.group("short") is not None:
            self._short(m.group("short"))

    def _short(self, s: str) -> None:
        if s == "7":
            self.saved = (self.x, self.y, self.style)
        elif s == "8":
            self.x, self.y, self.style = self.saved
            self.x, self.y, self.wrap = min(self.x, self.cols - 1), min(self.y, self.rows - 1), False
        elif s == "D":
            self._linefeed()
        elif s == "E":
            self.x = 0
            self._linefeed()
        elif s == "M":
            if self.y == self.top:
                self._scroll_down(1)
            elif self.y > 0:
                self.y -= 1
        elif s == "c":
            self.reset()

    def _csi(self, pre: str, args: str, mid: str, fin: str) -> None:
        if mid:
            return
        ps = [int(p) if p.isdigit() else 0 for p in args.replace(":", ";").split(";")] if args else []

        def p(i: int = 0, default: int = 1) -> int:
            v = ps[i] if i < len(ps) else 0
            return v or default

        if pre == "?":
            if fin in "hl":
                self._mode(ps, fin == "h")
            return
        if pre:
            return
        if fin != "m":
            self.wrap = False
        if fin == "m":
            self._sgr(ps)
        elif fin in "Hf":
            self.y, self.x = min(p(0) - 1, self.rows - 1), min(p(1) - 1, self.cols - 1)
        elif fin == "A":
            self.y = max(0, self.y - p())
        elif fin in "Be":
            self.y = min(self.rows - 1, self.y + p())
        elif fin in "Ca":
            self.x = min(self.cols - 1, self.x + p())
        elif fin == "D":
            self.x = max(0, self.x - p())
        elif fin == "E":
            self.x, self.y = 0, min(self.rows - 1, self.y + p())
        elif fin == "F":
            self.x, self.y = 0, max(0, self.y - p())
        elif fin in "G`":
            self.x = min(p() - 1, self.cols - 1)
        elif fin == "d":
            self.y = min(p() - 1, self.rows - 1)
        elif fin == "J":
            how = p(0, 0)
            if how == 0:
                self._erase(self.y, self.x, self.cols)
                for r in range(self.y + 1, self.rows):
                    self._erase(r, 0, self.cols)
            elif how == 1:
                self._erase(self.y, 0, self.x + 1)
                for r in range(0, self.y):
                    self._erase(r, 0, self.cols)
            else:
                for r in range(self.rows):
                    self._erase(r, 0, self.cols)
        elif fin == "K":
            how = p(0, 0)
            self._erase(self.y, *((self.x, self.cols) if how == 0 else (0, self.x + 1) if how == 1 else (0, self.cols)))
        elif fin == "X":
            self._erase(self.y, self.x, self.x + p())
        elif fin == "@":
            r = self.buffer[self.y]
            n = min(p(), self.cols - self.x)
            r[self.x:self.cols] = [(" ", PLAIN)] * n + r[self.x:self.cols - n]
        elif fin == "P":
            r = self.buffer[self.y]
            n = min(p(), self.cols - self.x)
            r[self.x:self.cols] = r[self.x + n:self.cols] + [(" ", PLAIN)] * n
        elif fin == "L":
            if self.top <= self.y <= self.bottom:
                self._scroll_down(p(), self.y)
        elif fin == "M":
            if self.top <= self.y <= self.bottom:
                self._scroll_up(p(), self.y)
        elif fin == "S":
            self._scroll_up(p())
        elif fin == "T":
            self._scroll_down(p())
        elif fin == "r":
            top, bottom = p(0) - 1, p(1, self.rows) - 1
            if 0 <= top < bottom < self.rows:
                self.top, self.bottom = top, bottom
                self.x = self.y = 0
        elif fin == "s":
            self.saved = (self.x, self.y, self.style)
        elif fin == "u":
            self.x, self.y, self.style = self.saved
        elif fin == "b":
            self._print(self.last * min(p(), self.cols * self.rows))

    def _mode(self, ps: List[int], on: bool) -> None:
        for mode in ps:
            if mode == 7:
                self.autowrap = on
            elif mode == 25:
                self.cursor_shown = on
            elif mode in (47, 1047, 1049):
                if mode == 1049 and on:
                    self.saved = (self.x, self.y, self.style)
                want = self.alt if on else self.main
                if want is not self.buffer:
                    if on:
                        self.alt = self._blank_buffer()
                        want = self.alt
                    self.buffer = want
                if mode == 1049 and not on:
                    self.x, self.y, self.style = self.saved
                self.wrap = False
            elif mode == 1048:
                if on:
                    self.saved = (self.x, self.y, self.style)
                else:
                    self.x, self.y, self.style = self.saved

    def _sgr(self, ps: List[int]) -> None:
        st = self.style.__dict__.copy() if ps else {}
        ps = ps or [0]
        i = 0
        while i < len(ps):
            v = ps[i]
            if v == 0:
                st = {}
            elif v == 1:
                st["bold"] = True
            elif v == 2:
                st["faint"] = True
            elif v == 3:
                st["italic"] = True
            elif v == 7:
                st["inverse"] = True
            elif v == 22:
                st["bold"] = st["faint"] = False
            elif v == 23:
                st["italic"] = False
            elif v == 27:
                st["inverse"] = False
            elif 30 <= v <= 37 or 90 <= v <= 97:
                st["fg"] = str(v - 30 if v < 90 else v - 82)
            elif 40 <= v <= 47 or 100 <= v <= 107:
                st["bg"] = str(v - 40 if v < 100 else v - 92)
            elif v == 39:
                st["fg"] = None
            elif v == 49:
                st["bg"] = None
            elif v in (38, 48) and i + 1 < len(ps):
                n = 3 if ps[i + 1] == 5 else 5 if ps[i + 1] == 2 else 1
                st["fg" if v == 38 else "bg"] = ";".join(map(str, ps[i + 1:i + n]))
                i += n - 1
            i += 1
        self.style = Style(**st)
