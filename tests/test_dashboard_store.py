"""store.py: the dashboard's database -- every table declared once, made at its first write and given its columns
since, what each does when an actor moves group, a group is merged or an actor is discarded, and a locked database
never read as nothing kept."""
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ag_dashboard import avatars, hiding, saved, seen, store, tasks, titles  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

DASHBOARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ag_dashboard")


class StoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.was = dashboard_home.HOME
        dashboard_home.HOME = os.path.join(self.tmp.name, "ag")

    def tearDown(self):
        dashboard_home.HOME = self.was
        self.tmp.cleanup()

    def rows(self, table, *columns):
        with store.reading() as conn:
            return sorted(conn.execute(f"SELECT {', '.join(columns or ('gatherer',))} FROM {table}"))

    def put(self, table, **row):
        with store.transaction(table) as conn:
            conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))

    def session(self, sid, gatherer):
        self.put("sessions", session_id=sid, gatherer=gatherer, harness="claude", cwd="/", permission_mode="auto",
                 created_at="2026-01-01", status="stopped")

    def branch(self, sid, gatherer):
        self.put("branches", session_id=sid, gatherer=gatherer, project="/p", worktree=f"/w/{sid}", branch=f"ag/{sid}",
                 start="main", created=0)


class DeclaredTest(StoreBase):
    def test_every_table_the_dashboard_makes_is_declared_by_a_module_the_store_loads(self):
        made, owners = set(), set()
        for name in os.listdir(DASHBOARD):
            if name.endswith(".py") and name != "store.py":
                with open(os.path.join(DASHBOARD, name), encoding="utf-8") as fh:
                    found = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", fh.read())
                made |= set(found)
                if found:
                    owners.add(name[:-3])
        with store.transaction() as conn:                 # loads every owner (a move, merge or discard does)
            list(store._present(conn))
        self.assertEqual(owners, set(store.OWNERS))
        made.add(store.TABLES["folders_in_home"].name)    # its CREATE is made from a constant
        self.assertEqual(made, set(store.TABLES))

    def test_a_table_naming_a_group_says_what_a_merge_does_to_it(self):
        with self.assertRaisesRegex(ValueError, "names a group"):
            store.table("t_unsaid", "CREATE TABLE IF NOT EXISTS t_unsaid (gatherer TEXT NOT NULL, x TEXT)")
        self.assertNotIn("t_unsaid", store.TABLES)
        try:                                              # a name with "gatherer" in it is no column of one
            store.table("t_gatherer_like", "CREATE TABLE IF NOT EXISTS t_gatherer_like (id INTEGER, name TEXT)")
        finally:
            store.TABLES.pop("t_gatherer_like", None)


class MadeTest(StoreBase):
    def test_nothing_is_made_by_a_read(self):
        self.assertEqual((saved.stored(), seen.stored(), hiding.stored(), tasks.stored()), ({}, None, {}, {}))
        self.assertFalse(os.path.exists(store.path()))
        saved.choose("g", "c1", True)
        self.assertEqual(seen.stored(), None)             # its table not made yet: "never kept", not "nothing seen"
        self.assertEqual(saved.stored(), {"g": {"c1": saved.stored()["g"]["c1"]}})

    def test_a_table_from_before_is_given_the_columns_added_since(self):
        os.makedirs(dashboard_home.HOME)
        conn = sqlite3.connect(store.path())
        conn.execute("CREATE TABLE avatars (gatherer TEXT NOT NULL, channel TEXT NOT NULL, avatar TEXT NOT NULL, "
                     "at TEXT NOT NULL, PRIMARY KEY (gatherer, channel))")
        conn.execute("INSERT INTO avatars VALUES ('g', 'c1', 'animals/fox', 'then')")
        conn.commit()
        conn.close()
        self.assertEqual(avatars.kept(), ({("g", "c1"): "animals/fox"}, {}))   # read before: no `said` yet
        store.write("avatars").close()
        with store.reading() as conn:
            self.assertIn("said", store.columns(conn, "avatars"))

    def test_a_table_made_again_by_another_is_looked_at_again(self):
        store.write("titles").close()
        conn = sqlite3.connect(store.path())
        conn.execute("DROP TABLE titles")
        conn.commit()
        conn.close()
        titles.give("g", "Group G")                       # the schema changed since: made again, not taken as there
        self.assertEqual(titles.stored(), {"g": "Group G"})


class RemadeTest(StoreBase):
    def test_a_file_made_again_at_the_same_path_is_prepared_again_whatever_its_inode_and_schema_version(self):
        """A dashboard.db deleted and made again at its path, an older table in it: its columns added since are added,
        though the new file has the old one's inode (Linux gives a freed inode out again) and schema version."""
        from ag_dashboard import sessions
        conn = store.write("sessions")                        # made, and known to this process as prepared
        conn.close()
        st = os.stat(store.path())
        with store.reading() as c:
            version = c.execute("PRAGMA schema_version").fetchone()[0]
        os.remove(store.path())
        conn = sqlite3.connect(store.path())
        conn.execute(sessions.SCHEMA[:sessions.SCHEMA.index(",\n    kept")] + "\n)")   # the columns before `kept`
        conn.execute(f"PRAGMA schema_version = {version}")    # as the old file's
        conn.commit()
        conn.close()
        real = os.stat
        same = lambda p, *a, **k: st if p == store.path() else real(p, *a, **k)   # noqa: E731 -- the old inode
        with unittest.mock.patch.object(store.os, "stat", same):
            conn = store.write("sessions")
            try:
                self.assertIn("kept", store.columns(conn, "sessions"))
            finally:
                conn.close()


class FollowTest(StoreBase):
    def test_an_actor_that_moves_takes_every_row_kept_of_it_and_its_task(self):
        for c in ("c1", "c2"):
            self.session(c, "a")
            self.branch(c, "a")
            saved.choose("a", c, True)
            seen.look([["a", c, 1.0]])
        tasks.add("a", "c1", ["app:notes"])               # c1's task, with an app
        with store.transaction() as conn:
            store.move_actors(conn, "a", "b", ["c1", "app:notes"])
        for table, column in (("sessions", "session_id"), ("branches", "session_id"), ("saved", "channel"),
                              ("seen", "channel")):
            with self.subTest(table=table):
                self.assertEqual(self.rows(table, "gatherer", column), [("a", "c2"), ("b", "c1")])
        self.assertEqual(self.rows("tasked", "gatherer", "channel"), [("b", "app:notes"), ("b", "c1")])   # c2: in none
        self.assertEqual(self.rows("tasks", "gatherer"), [("b",)])

    def test_a_group_merged_into_another_is_followed_as_each_table_says(self):
        self.session("c1", "a")
        self.branch("c1", "a")
        saved.choose("a", "c1", True)
        hiding.choose("a", "hidden")
        titles.give("a", "Group A")
        titles.give("b", "Group B")
        self.put("gatherers_filed", gatherer="a", folder=1, at="then")
        self.put("projects", gatherer="a", path="/p", remote=None, added=1)
        self.put("projects", gatherer="a", path="/q", remote=None, added=1)
        self.put("projects", gatherer="b", path="/p", remote="kept", added=2)
        self.put("tasks_grouped", gatherer="a", at="then")
        self.put("watches", gatherer="a", watcher="w", target="c1", created=0)
        with store.transaction() as conn:
            store.merge_group(conn, "a", "b")
        moved = {t: self.rows(t) for t in ("sessions", "branches", "saved")}
        self.assertEqual(moved, {t: [("b",)] for t in moved})                       # an actor's rows: the group's now
        self.assertEqual((hiding.stored(), titles.stored()), ({}, {"b": "Group B"}))  # its own choices: gone with it
        self.assertEqual((self.rows("gatherers_filed"), self.rows("tasks_grouped")), ([], []))
        self.assertEqual(self.rows("projects", "gatherer", "path", "remote"),          # joined, the other's kept as it is
                         [("b", "/p", "kept"), ("b", "/q", None)])
        self.assertEqual(self.rows("watches"), [("a",)])  # a watch follows its actors itself (coordination.py)

    def test_a_discarded_actor_s_rows_go_but_its_branch_stays(self):
        self.session("c1", "a")
        self.branch("c1", "a")
        saved.choose("a", "c1", True)
        with store.transaction() as conn:
            store.discard_actor(conn, "a", "c1")
        self.assertEqual((self.rows("sessions"), self.rows("saved"), self.rows("branches")), ([], [], [("a",)]))


class LockedTest(StoreBase):
    def test_a_locked_database_is_an_error_not_nothing_kept(self):
        saved.choose("g", "c1", True)
        hold = sqlite3.connect(store.path(), isolation_level=None)
        hold.execute("BEGIN EXCLUSIVE")
        self.addCleanup(hold.close)
        with unittest.mock.patch.object(store, "TIMEOUT", 0.1):
            for read in (saved.stored, hiding.stored, titles.stored, tasks.stored, avatars.kept):
                with self.subTest(read=read.__module__):
                    with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                        read()
        hold.execute("ROLLBACK")
        self.assertEqual(list(saved.stored()["g"]), ["c1"])


if __name__ == "__main__":
    unittest.main()
