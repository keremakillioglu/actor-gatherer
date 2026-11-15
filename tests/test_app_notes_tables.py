"""Tables in the Notes app (notebook.py's TABLE): the table block, the ops on its rows and columns, the markdown agents
read and write, and an agent's table written over one there changing only what differs. The panel's side is in
frontend/e2e/notes-tables.spec.ts."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_apps.notes import notebook as nb  # noqa: E402
from ag_apps.notes.backend import NotesApp  # noqa: E402
from app_kit import Caller, Instance  # noqa: E402

from test_app_notes import BookBase, Host  # noqa: E402


def table(tid="tabletab", rows=(("Feature", "Who"), ("Links", "Ada")), **more):
    """A table block: columns c1.., rows r1.., the cells given (a row's words, in column order)."""
    width = max(len(r) for r in rows)
    cols = [{"id": f"colcol{j + 1}"} for j in range(width)]
    made = [{"id": f"rowrow{i + 1}", "cells": {cols[j]["id"]: w for j, w in enumerate(r) if w}}
            for i, r in enumerate(rows)]
    return {"id": tid, "type": "table", "cols": cols, "rows": made, **more}


def words(b):
    """A table's cells, row by row, in column order."""
    return [[r["cells"].get(c["id"], "") for c in b["cols"]] for r in b["rows"]]


class TableBlockTest(BookBase):
    def test_a_table_is_kept_clean_with_a_header_row_unless_said(self):
        p = self.page(blocks=[table(rows=(("<b>Bold</b><script>x</script>", "<div>a</div><div>b</div>"),
                                          ("", "two")))])
        b = p["blocks"][0]
        self.assertEqual(b["type"], "table")
        self.assertEqual(words(b), [["<b>Bold</b>", "a<br>b"], ["", "two"]])
        self.assertEqual(b["rows"][1]["cells"], {"colcol2": "two"})               # an empty cell is not kept
        self.assertTrue(b["head"])
        self.assertFalse(b["head_col"])
        self.assertEqual(b["text"], "")

    def test_a_table_made_bare_has_three_rows_and_columns(self):
        p = self.page(blocks=[{"id": "tabletab", "type": "table"}])
        self.assertEqual((len(p["blocks"][0]["cols"]), len(p["blocks"][0]["rows"])), (3, 3))

    def test_what_a_table_is_not(self):
        for bad in ({"cols": [], "rows": [{"id": "rowrow01"}]}, {"cols": [{"id": "colcol01"}], "rows": []},
                    {"cols": "x", "rows": []}, {"cols": [{"id": "BAD"}], "rows": [{"id": "rowrow01"}]},
                    {"cols": [{"id": "colcol01", "w": "wide"}], "rows": [{"id": "rowrow01"}]},
                    {"cols": [{"id": "colcol01"}], "rows": [{"id": "rowrow01", "cells": {"colcol01": 3}}]},
                    {"cols": [{"id": f"colcol{j:02}"} for j in range(nb.MAX_COLS + 1)], "rows": [{"id": "rowrow01"}]}):
            with self.subTest(bad=bad):
                with self.assertRaises(nb.NotebookError):
                    self.book.apply([{"op": "page.new", "page": {"id": "pagepage"},
                                      "blocks": [{"id": "tabletab", "type": "table", **bad}]}])

    def test_a_column_width_is_kept_in_range_and_cells_of_no_column_dropped(self):
        t = table()
        t["cols"][0]["w"] = 9
        t["cols"][1]["w"] = 260.7
        t["rows"][0]["cells"]["nocolumn"] = "lost"
        b = self.page(blocks=[t])["blocks"][0]
        self.assertEqual([c.get("w") for c in b["cols"]], [nb.COL_W[0], 260])
        self.assertNotIn("nocolumn", b["rows"][0]["cells"])

    def test_a_table_is_sent_to_no_one_but_may_name_its_source(self):
        b = self.page(blocks=[{**table(), "to": "chan-1", "work": True, "source": "chan-1", "source_at": 5}])
        b = b["blocks"][0]
        self.assertNotIn("calls", b)
        self.assertNotIn("work", b)
        self.assertEqual(b["source"], "chan-1")
        self.assertFalse(nb.is_work(b))

    def test_block_put_changes_its_header_flags_and_keeps_the_rest(self):
        self.page(blocks=[table()])
        self.book.apply([{"op": "block.put", "page": "pagepage", "block": {"id": "tabletab", "head": False,
                                                                          "head_col": True}}])
        b = self.book.page("pagepage")["blocks"][0]
        self.assertEqual((b["head"], b["head_col"]), (False, True))
        self.assertEqual(words(b), [["Feature", "Who"], ["Links", "Ada"]])


class TableOpsTest(BookBase):
    def setUp(self):
        super().setUp()
        self.page(blocks=[table(), {"id": "textline", "type": "text", "text": "after"}])

    def op(self, kind, **rest):
        v, done = self.book.apply([{"op": kind, "page": "pagepage", "block": "tabletab", **rest}])
        return done

    def t(self):
        return self.book.page("pagepage")["blocks"][0]

    def test_a_cell_typed_changes_that_cell_alone(self):
        done = self.op("row.put", row={"id": "rowrow2", "cells": {"colcol1": "Page <i>links</i>"}})
        self.assertEqual(done, [{"op": "row.put", "page": "pagepage", "block": "tabletab",
                                 "row": {"id": "rowrow2", "cells": {"colcol1": "Page <i>links</i>"}}}])
        self.assertEqual(words(self.t()), [["Feature", "Who"], ["Page <i>links</i>", "Ada"]])
        self.assertEqual(self.op("row.put", row={"id": "rowrow2", "cells": {"colcol1": "Page <i>links</i>"}}), [])
        self.op("row.put", row={"id": "rowrow2", "cells": {"colcol2": ""}})          # emptied: not kept
        self.assertEqual(self.t()["rows"][1]["cells"], {"colcol1": "Page <i>links</i>"})

    def test_a_cell_typed_is_kept_and_one_of_a_row_or_column_gone_is_skipped(self):
        done = self.op("cell.put", row="rowrow2", col="colcol1", text="Page <i>links</i><script>x</script>")
        self.assertEqual(done, [{"op": "cell.put", "page": "pagepage", "block": "tabletab", "row": "rowrow2",
                                 "col": "colcol1", "text": "Page <i>links</i>"}])
        self.assertEqual(self.op("cell.put", row="rowrow2", col="colcol1", text="Page <i>links</i>"), [])
        self.op("cell.put", row="rowrow2", col="colcol2", text="")
        self.assertEqual(self.t()["rows"][1]["cells"], {"colcol1": "Page <i>links</i>"})
        self.op("row.delete", row="rowrow2")
        self.assertEqual(self.op("cell.put", row="rowrow2", col="colcol1", text="back?"), [])
        self.assertEqual(self.op("cell.put", row="rowrow1", col="gonecol1", text="back?"), [])
        self.assertEqual(len(self.t()["rows"]), 1)

    def test_two_cells_typed_at_once_elsewhere_both_stay(self):
        self.book.apply([{"op": "row.put", "page": "pagepage", "block": "tabletab",
                          "row": {"id": "rowrow1", "cells": {"colcol2": "Owner"}}},
                         {"op": "row.put", "page": "pagepage", "block": "tabletab",
                          "row": {"id": "rowrow2", "cells": {"colcol1": "Page links"}}}])
        self.assertEqual(words(self.t()), [["Feature", "Owner"], ["Page links", "Ada"]])

    def test_rows_added_moved_and_deleted(self):
        done = self.op("row.put", row={"id": "rowrow3", "cells": {"colcol1": "Tables"}}, after="rowrow1")
        self.assertEqual(done[0]["after"], "rowrow1")
        self.assertEqual([r["id"] for r in self.t()["rows"]], ["rowrow1", "rowrow3", "rowrow2"])
        self.op("row.put", row={"id": "rowrow0"}, after="")
        self.op("row.move", row="rowrow0", after="rowrow2")
        self.assertEqual([r["id"] for r in self.t()["rows"]], ["rowrow1", "rowrow3", "rowrow2", "rowrow0"])
        self.op("row.delete", row="rowrow3")
        self.assertEqual(words(self.t()), [["Feature", "Who"], ["Links", "Ada"], ["", ""]])

    def test_columns_added_with_cells_widened_moved_and_deleted_with_theirs(self):
        done = self.op("col.put", col={"id": "colcol3"}, cells={"rowrow1": "Status", "rowrow2": "Merged",
                                                                "gonerow1": "x"}, after="colcol1")
        self.assertEqual(done[0]["cells"], {"rowrow1": "Status", "rowrow2": "Merged"})
        self.assertEqual(words(self.t()), [["Feature", "Status", "Who"], ["Links", "Merged", "Ada"]])
        self.op("col.put", col={"id": "colcol3", "w": 180})
        self.assertEqual(self.t()["cols"][1], {"id": "colcol3", "w": 180})
        self.op("col.put", col={"id": "colcol3", "w": None})
        self.assertEqual(self.t()["cols"][1], {"id": "colcol3"})
        self.op("col.move", col="colcol1", after="colcol2")
        self.assertEqual(words(self.t()), [["Status", "Who", "Feature"], ["Merged", "Ada", "Links"]])
        self.op("col.delete", col="colcol2")
        self.assertEqual(words(self.t()), [["Status", "Feature"], ["Merged", "Links"]])
        self.assertNotIn("colcol2", self.t()["rows"][0]["cells"])

    def test_a_table_keeps_a_row_and_a_column(self):
        self.op("col.delete", col="colcol2")
        self.op("row.delete", row="rowrow2")
        for kind, rest in (("col.delete", {"col": "colcol1"}), ("row.delete", {"row": "rowrow1"})):
            with self.subTest(kind=kind):
                with self.assertRaises(nb.NotebookError):
                    self.op(kind, **rest)

    def test_an_op_on_a_row_column_or_table_gone_is_skipped(self):
        self.assertEqual(self.op("row.put", row={"id": "rowrow2", "cells": {"nocolumn": "x"}}), [])
        self.assertEqual(self.op("row.move", row="norowhere", after=""), [])
        self.assertEqual(self.op("col.delete", col="nocolumn"), [])
        v, done = self.book.apply([{"op": "row.put", "page": "pagepage", "block": "nonesuch",
                                    "row": {"id": "rowrow1"}}])
        self.assertEqual(done, [])

    def test_a_table_op_on_a_line_is_refused(self):
        with self.assertRaises(nb.NotebookError):
            self.book.apply([{"op": "row.put", "page": "pagepage", "block": "textline", "row": {"id": "rowrow1"}}])
        with self.assertRaises(nb.NotebookError):
            self.op("row.put", row={"id": "BAD"})

    def test_a_table_holds_so_many_rows(self):
        for i in range(nb.MAX_ROWS - 2):
            self.op("row.put", row={"id": f"rowmore{i:04}"})
        with self.assertRaises(nb.NotebookError):
            self.op("row.put", row={"id": "rowtoomany"})


class TableMarkdownTest(unittest.TestCase):
    def test_agents_read_a_table_as_markdown_its_id_on_its_first_row(self):
        b = nb._block(table(rows=(("Feature", "Notes"), ("**x**", "a <b>b</b> | c<br>d"), ("", "only"))), None, "t")
        self.assertEqual(nb.markdown_lines([b]), [
            "[tabletab] | Feature | Notes |",
            "| --- | --- |",
            "| **x** | a **b** \\| c<br>d |",
            "|  | only |"])

    def test_markdown_tables_read_as_tables_and_back(self):
        md = ("Before\n[tabletab] | Feature | Who |\n|:---|---:|\n| **Bold** | a \\| b |\n| short |\n"
              "| [Plans](https://x.org) | three | extra |\nAfter")
        bs = nb.blocks_from_markdown(md)
        self.assertEqual([b["type"] for b in bs], ["text", "table", "text"])
        t = bs[1]
        self.assertEqual(len(t["cols"]), 3)                                        # the widest row's
        self.assertEqual(words(t), [["Feature", "Who", ""], ["<b>Bold</b>", "a | b", ""], ["short", "", ""],
                                    ['<a href="https://x.org">Plans</a>', "three", "extra"]])
        self.assertTrue(t["head"])
        again = nb.blocks_from_markdown("\n".join(nb.markdown_lines([nb._block({**t, "id": "tabletab"}, None, "t")])))
        self.assertEqual(words(again[0]), words(t))

    def test_what_is_not_a_table(self):
        for md in ("a | b\nnot dashes", "a | b\n---", "| a |", "```\n| a |\n|---|\n```"):
            with self.subTest(md=md):
                self.assertNotIn("table", [b["type"] for b in nb.blocks_from_markdown(md)])

    def test_a_table_over_one_changes_only_what_differs(self):
        old = nb._block(table(rows=(("A", "B"), ("1", "2"), ("3", "4"))), None, "t")
        old["cols"][1]["w"] = 200
        same = nb.blocks_from_markdown("\n".join(nb.markdown_lines([old])))[0]
        self.assertEqual(nb.table_ops("pagepage", old, same), [])
        new = nb.blocks_from_markdown("| A | B | C |\n|-|-|-|\n| 1 | two | x |")[0]
        ops = nb.table_ops("pagepage", old, new)
        self.assertEqual([o["op"] for o in ops], ["col.put", "row.put", "row.put", "row.delete"])
        cid = ops[0]["col"]["id"]
        self.assertEqual(ops[1]["row"], {"id": "rowrow1", "cells": {cid: "C"}})
        self.assertEqual(ops[2]["row"], {"id": "rowrow2", "cells": {"colcol2": "two", cid: "x"}})
        self.assertEqual(ops[3]["row"], "rowrow3")
        fewer = nb.blocks_from_markdown("| A |\n|-|\n| 1 |\n| 3 |\n| 5 |")[0]
        ops = nb.table_ops("pagepage", old, fewer)
        self.assertEqual([o["op"] for o in ops], ["row.put", "col.delete"])
        self.assertEqual(ops[0]["after"], "rowrow3")
        self.assertEqual(ops[0]["row"]["cells"], {"colcol1": "5"})

    def test_what_the_user_changed_since_the_agent_read_it_stays(self):
        old = nb._block(table(rows=(("A", "B"), ("1", "2"), ("3", "4"))), None, "t")
        read = nb.table_seen(old)
        now = nb._block(table(rows=(("A", "B"), ("one", "2"), ("3", "4"))), None, "t")   # the user typed "one"
        now["rows"].insert(1, {"id": "userrow1", "cells": {"colcol1": "mine"}})          # and added a row
        del now["rows"][3]                                                                 # and deleted 3 | 4
        agent = nb.blocks_from_markdown("| A | B |\n|-|-|\n| 1 | two |\n| 3 | four |")[0]
        ops = nb.table_ops("pagepage", now, agent, read)
        self.assertEqual(ops, [{"op": "row.put", "page": "pagepage", "block": "tabletab",
                                "row": {"id": "rowrow2", "cells": {"colcol2": "two"}}}])
        shorter = nb.blocks_from_markdown("| A | B |\n|-|-|")[0]
        self.assertEqual([(o["op"], o["row"]) for o in nb.table_ops("pagepage", now, shorter, read)],
                         [("row.delete", "rowrow2")])                  # the user's row, unread, kept


class TableToolsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.app = NotesApp()
        self.host = Host(self.dir)
        self.app.start(self.host)
        self.inst = self.app.open(Instance(id="0123456789abcdef", app="notes", gatherer="g"), {})

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def call(self, tool, channel="chan-1", **args):
        got = self.app.call(self.inst, tool, args, Caller(channel=channel, gatherer="g"))
        self.assertFalse(got.is_error, got.content[0]["text"])
        return got.content[0]["text"]

    def test_an_agent_adds_a_table_reads_it_and_changes_one_cell(self):
        self.call("add", title="Trips", markdown="Where:\n| City | Flight |\n| --- | --- |\n| Lisbon | Ask |")
        book = self.app.book("g")
        p = book.page("Trips")
        t = p["blocks"][1]
        self.assertEqual(words(t), [["City", "Flight"], ["Lisbon", "Ask"]])
        text = self.call("read", page="Trips")
        self.assertIn(f"[{t['id']}] | City | Flight |\n| --- | --- |\n| Lisbon | Ask |", text)
        # the user types in the other cell meanwhile: the agent's rewrite leaves it as the user has it
        book.apply([{"op": "row.put", "page": p["id"], "block": t["id"],
                     "row": {"id": t["rows"][1]["id"], "cells": {t["cols"][0]["id"]: "Lisboa"}}}])
        self.host.told.clear()
        self.call("change", page="Trips", block=t["id"], markdown="| City | Flight |\n|---|---|\n| Lisbon | Booked |")
        t = book.page("Trips")["blocks"][1]
        self.assertEqual(words(t), [["City", "Flight"], ["Lisboa", "Booked"]])
        self.assertEqual([o["op"] for o in self.host.told[0]["ops"]], ["row.put"])
        self.assertEqual(self.host.told[0]["ops"][0]["row"]["cells"], {t["cols"][1]["id"]: "Booked"})

    def test_a_table_from_the_conversation_names_its_source_and_a_line_over_a_table_replaces_it(self):
        self.call("add", title="Trips", markdown="| a | b |\n|---|---|\n| 1 | 2 |", from_conversation=True)
        book = self.app.book("g")
        t = book.page("Trips")["blocks"][0]
        self.assertEqual(t["source"], "chan-1")
        self.call("change", page="Trips", block=t["id"], markdown="| a | b |\n|---|---|\n| 1 | 3 |",
                  from_conversation=True, channel="chan-2")
        self.assertEqual(book.page("Trips")["blocks"][0]["source"], "chan-2")
        self.call("change", page="Trips", block=t["id"], markdown="just words")
        b = book.page("Trips")["blocks"][0]
        self.assertEqual((b["type"], b["text"]), ("text", "just words"))
        self.assertNotIn("rows", b)

    def test_pasted_markdown_is_parsed_into_a_table(self):
        r = self.app.request(self.inst, "POST", "parse", {}, b'{"markdown": "| x | y |\\n|---|---|\\n| 1 | 2 |"}')
        import json
        got = json.loads(r.body)["blocks"]
        self.assertEqual(got[0]["type"], "table")
        self.assertEqual(words(got[0]), [["x", "y"], ["1", "2"]])


if __name__ == "__main__":
    unittest.main()
