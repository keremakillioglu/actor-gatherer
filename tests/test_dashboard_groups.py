"""Moving actors and folders from one group to another (ag_dashboard/groups.py), in the home's one database: a `group`
record in each moved actor's channel, then the dashboard's own rows of them under the group's name."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ag.ag_harness.store import paths  # noqa: E402
import app_kit  # noqa: E402
from ag_dashboard import actions, app_agents, app_host, coordinators, data, folders, gatherer_folders, group_admin, groups, merges, naming, saved, sessions, tasks, titles, tool_gateway  # noqa: E402
from replies import insert  # noqa: E402
from test_dashboard_app_host import NOTES, insert_here, write_app  # noqa: E402
import test_home_db  # noqa: E402

REAL_INSERT = actions.insert                                      # GroupsTest's tests have it run here instead


class GroupsTest(unittest.TestCase):
    """Groups `a` (c1, c3) and `b` (c2) in the home's one database; records put in by ag as the dashboard would."""

    def setUp(self):
        test_home_db.MergedHomeTest.setUp(self)
        self.addCleanup(test_home_db.MergedHomeTest.tearDown, self)
        self.recorded = []
        for patch in (unittest.mock.patch.object(actions, "insert", side_effect=self.insert),
                      unittest.mock.patch.object(tool_gateway, "HOST", None)):           # no apps run here
            patch.start()
            self.addCleanup(patch.stop)

    def insert(self, gatherer, events):
        """actions.insert, in this process: each event in the channel its own properties name."""
        self.recorded.append((gatherer, events))
        insert(self.m, gatherer, {}, events)
        return [None] * len(events)

    def events(self, kind):
        return [e for _, events in self.recorded for e in events if e["type"] == kind]

    def members(self, group):
        conn = data._connect(group)
        try:
            return sorted(data.members(conn, group))
        finally:
            conn.close()

    def rows(self, table):
        conn = sqlite3.connect(sessions.db_path())
        try:
            return sorted(conn.execute(f"SELECT gatherer, channel FROM {table}"))
        finally:
            conn.close()

    def test_a_plan_says_who_moves_and_changes_nothing(self):
        got = groups.plan("a", "b", ["c1"])
        self.assertEqual((got["actors"], got["folder"]), (["c1"], None))
        self.assertEqual((got["before"], got["after"]), ({"a": 2, "b": 1}, {"a": 1, "b": 2}))
        self.assertEqual((self.members("a"), self.members("b")), (["c1", "c3"], ["c2"]))
        self.assertEqual(self.events("group"), [])

    def test_a_move_is_one_call_to_ag(self):
        work = folders.make("a", "Work")
        folders.file("a", ["c1", "c3"], work)
        self.recorded.clear()
        groups.move("a", "b", folder=work)
        self.assertEqual(len(self.recorded), 1)

    def test_an_actor_moved_is_in_its_new_group_with_its_rows(self):
        saved.choose("a", "c1", True)
        into = folders.make("b", "Inbox")
        groups.move("a", "b", ["c1"], into=into)
        self.assertEqual((self.members("a"), self.members("b")), (["c3"], ["c1", "c2"]))
        [event] = [e for e in self.events("group") if e["payload"]["was"] == "a"]
        self.assertEqual(event["properties"], {"channel": "c1"})
        self.assertEqual({k: event["payload"][k] for k in ("group", "was", "folder")}, {"group": "b", "was": "a", "folder": into})
        self.assertIn("c1", event["id"])                          # a read returns an id once, whatever its channel
        self.assertEqual(self.rows("saved"), [("b", "c1")])
        self.assertEqual(folders.of("b")["filed"], {"c1": into})
        self.assertEqual(folders.of("a")["filed"], {})

    def test_a_folder_moves_with_its_folders_and_every_actor_in_them(self):
        top = folders.make("a", "Work")
        inner = folders.make("a", "Inner", top)
        folders.file("a", ["c1"], top)
        folders.file("a", ["c3"], inner)
        got = groups.move("a", "b", folder=top)
        self.assertEqual(got["actors"], ["c1", "c3"])
        self.assertEqual((self.members("a"), self.members("b")), ([], ["c1", "c2", "c3"]))
        self.assertEqual(folders.of("a"), {"folders": [], "filed": {}})
        moved = {f["name"]: f.get("parent") for f in folders.of("b")["folders"]}
        self.assertEqual(moved, {"Work": None, "Inner": top})
        self.assertEqual(folders.of("b")["filed"], {"c1": top, "c3": inner})

    def crew(self, channel, gatherer, over):
        """A coordinator agent's session over `over` (sessions.py's table), as coordination.py's `ensure` makes one."""
        conn = sqlite3.connect(sessions.db_path())
        try:
            conn.execute(sessions.SCHEMA)
            have = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
            for name, kind in sessions.ADDED:
                if name not in have:
                    conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {kind}")
            conn.execute(f"INSERT INTO sessions ({', '.join(sessions.COLUMNS)}) VALUES (?, ?, 'claude', '/', 'auto', "
                         "'2026-01-01T00:00:00Z', 0, 'stopped', NULL, 0, NULL, NULL, 0, 'coordinator', ?)",
                         (channel, gatherer, over))
            conn.commit()
        finally:
            conn.close()
        insert(self.m, gatherer, {}, [{"type": "group", "id": f"group:{channel}:first", "properties": {"channel": channel},
                                       "payload": {"group": gatherer}}])

    def over(self, channel):
        return next((r["gatherer"], r["over"]) for r in sessions.stored() if r["session_id"] == channel)

    def test_a_folder_s_coordinator_agent_goes_with_it_and_one_over_the_group_stays(self):
        top = folders.make("a", "Work")
        inner = folders.make("a", "Inner", top)
        folders.file("a", ["c1"], inner)
        self.crew("k1", "a", f"folder:{inner}")                   # over a folder that moves
        self.crew("k2", "a", None)                                 # over the group: stays
        got = groups.move("a", "b", folder=top)
        self.assertEqual(got["actors"], ["c1", "k1"])
        self.assertEqual((self.members("a"), self.members("b")), (["c3", "k2"], ["c1", "c2", "k1"]))
        self.assertEqual((self.over("k1"), self.over("k2")), (("b", f"folder:{inner}"), ("a", None)))
        [record] = [e for e in self.events("group") if e["properties"]["channel"] == "k1" and "was" in e["payload"]]
        self.assertIsNone(record["payload"]["folder"])            # in no folder there, as it is in none
        self.assertNotIn("k1", folders.of("b")["filed"])

    def test_a_folder_made_a_group_makes_its_coordinator_agent_the_group_s(self):
        work = folders.make("a", "Work")
        folders.file("a", ["c1"], work)
        self.crew("k1", "a", f"folder:{work}")
        with unittest.mock.patch.object(groups.sessions, "new_gatherer", side_effect=self.made):
            got = groups.split("a", work)
        self.assertEqual(self.over("k1"), (got["group"], None))
        self.assertIn("k1", self.members(got["group"]))

    def test_a_task_moves_whole(self):
        task = tasks.add("a", "c1", ["c3"])
        got = groups.move("a", "b", ["c1"])
        self.assertEqual(got["actors"], ["c1", "c3"])
        self.assertEqual(self.members("a"), [])
        self.assertEqual(tasks.stored()["b"]["tasked"], {"c1": task, "c3": task})
        self.assertNotIn("a", tasks.stored())

    def test_nothing_of_the_dashboard_s_changes_when_ag_did_not_take_the_record(self):
        saved.choose("a", "c1", True)
        with unittest.mock.patch.object(actions, "insert", side_effect=RuntimeError("no")):     # ag kept nothing
            with self.assertRaises(groups.GroupError):
                groups.move("a", "b", ["c1"])
        self.assertEqual(self.rows("saved"), [("a", "c1")])

    def test_a_folder_named_as_one_where_it_would_go_is_refused_before_anything(self):
        work = folders.make("a", "Work")
        folders.make("b", "work")
        with self.assertRaises(groups.GroupError):
            groups.move("a", "b", folder=work)
        self.assertEqual((self.events("group"), self.members("a")), ([], ["c1", "c3"]))

    def made(self, name):
        """sessions.new_gatherer, as `ag new` makes a group here: its config."""
        os.makedirs(os.path.join(paths.TRACE_DIR, name))
        with open(os.path.join(paths.TRACE_DIR, name, "gatherer.toml"), "w") as fh:
            fh.write('policy = "proactive_context_manager"\n')
        return {"name": name}

    def test_a_folder_outside_every_group_is_a_group_of_its_own(self):
        work = folders.make("a", "Work: notes")
        inner = folders.make("a", "Inner", work)
        folders.file("a", ["c1"], work)
        folders.file("a", ["c3"], inner)
        with unittest.mock.patch.object(groups.sessions, "new_gatherer", side_effect=self.made):
            got = groups.split("a", work)
        self.assertEqual(got, {"group": "Work_notes", "actors": ["c1", "c3"], "apps": [], "from": "a"})
        self.assertEqual(titles.stored()["Work_notes"], "Work: notes")          # named as the folder was
        self.assertEqual((self.members("a"), self.members("Work_notes")), ([], ["c1", "c3"]))
        self.assertEqual(folders.of("Work_notes"), {"folders": [{"id": inner, "parent": None, "name": "Inner", "closed": None}],
                                                    "filed": {"c3": inner}})   # the folder gone, what was in it at the top
        self.assertEqual(folders.of("a"), {"folders": [], "filed": {}})
        [moved] = [e for e in self.events("group") if e["payload"]["group"] != e["payload"]["was"]
                   and e["properties"]["channel"] == "c1"]
        self.assertEqual(moved["payload"]["group"], "Work_notes")

    def test_a_new_group_s_name_is_one_no_group_has(self):
        self.assertEqual(groups._group_name("b"), "b_2")
        self.assertEqual(groups._group_name("  ***  "), "group")

    def test_an_app_moves_only_where_its_host_runs(self):
        work = folders.make("a", "Work")
        folders.file("a", ["c1", "app:x1"], work)
        with unittest.mock.patch.object(groups.sessions, "new_gatherer", side_effect=self.made) as made:
            with self.assertRaises(groups.GroupError):
                groups.split("a", work)
            with self.assertRaises(groups.GroupError):
                groups.move("a", "b", folder=work)
        made.assert_not_called()
        self.assertEqual(self.members("a"), ["c1", "c3"])

    def test_an_actor_on_its_own_is_a_group_of_one(self):
        saved.choose("a", "c1", True)
        work = folders.make("a", "Work")
        folders.file("a", ["c1"], work)
        self.recorded.clear()
        self.assertEqual(groups.alone("a", "c1"), {"group": "self:c1", "actors": ["c1"], "apps": [], "from": "a",
                                                   "in": None, "folder": None})
        [(via, [event, placed])] = self.recorded                           # one call to ag, as the group it leaves
        self.assertEqual(placed["payload"], {"item": "group:self:c1", "group": "", "folder": None})   # at the list's top
        self.assertEqual((via, event["properties"]), ("a", {"channel": "c1"}))
        self.assertEqual({k: event["payload"][k] for k in ("group", "was", "folder")}, {"group": "self:c1", "was": "a", "folder": None})
        self.assertEqual((self.members("a"), self.members("self:c1")), (["c3"], ["c1"]))
        self.assertEqual(self.rows("saved"), [("self:c1", "c1")])
        self.assertEqual(folders.of("a")["filed"], {})                     # out of its folder too
        self.assertEqual(data.alone_names(), ["self:c1"])
        listed = {g["name"]: (g.get("alone", False), [a["channel"] for a in g["agents"]]) for g in data.home([])["gatherers"]}
        self.assertEqual(listed["self:c1"], (True, ["c1"]))
        self.assertEqual(listed["a"], (False, ["c3"]))

    def test_a_change_to_what_a_group_holds_counts_as_its_latest_change(self):
        old = "2026-01-01T00:00:00+00:00"
        conn = sqlite3.connect(paths.home_db())
        conn.execute("UPDATE events SET inserted_at = ?", (old,))             # every record so far: long ago
        conn.commit()
        conn.close()
        since = data._seconds(old)
        self.assertEqual({k: v for k, v in data.changed().items() if k in ("a", "b")}, {"a": since, "b": since})
        groups.move("a", "b", ["c1"])                                         # an actor moved from a to b: both changed
        now = data.changed()
        self.assertGreater(now["a"], since)
        self.assertGreater(now["b"], since)
        listed = {g["name"]: g for g in data.home([])["gatherers"]}
        self.assertEqual((listed["a"]["changed"], listed["b"]["changed"]), (now["a"], now["b"]))
        conn = sqlite3.connect(paths.home_db())
        conn.execute("UPDATE events SET inserted_at = ?", (old,))
        conn.commit()
        conn.close()
        folders.make("b", "Work")                                             # a folder made in b: b changed, not a
        now = data.changed()
        self.assertEqual(now["a"], since)
        self.assertGreater(now["b"], since)

    def test_an_actor_on_its_own_runs_under_the_group_it_left_and_comes_back(self):
        groups.alone("a", "c1")
        self.assertEqual(groups.launch_group("c1", "self:c1"), "a")         # ag runs it in a group of the home
        self.assertEqual(groups.launch_group("c3", "a"), "a")
        groups.move("self:c1", "b", ["c1"])
        self.assertEqual((self.members("b"), data.alone_names()), (["c1", "c2"], []))

    def test_an_actor_is_not_taken_out_with_others_of_its_task_nor_the_coordinator(self):
        tasks.add("a", "c1", ["c3"])
        with self.assertRaises(groups.GroupError):
            groups.alone("a", "c1")
        with unittest.mock.patch.object(groups.sessions, "stored", return_value=[{"session_id": "c3", "role": "coordinator"}]):
            with self.assertRaises(groups.GroupError):
                groups.alone("a", "c3")
        with self.assertRaises(groups.GroupError):
            groups.alone("a", "c2")                                         # b's, not a's
        self.assertEqual(self.members("a"), ["c1", "c3"])

    def test_what_is_written_of_an_actor_on_its_own_goes_through_ag_as_the_group_it_left(self):
        """ag keeps a config for the home's groups, and would make one -- a gatherer -- for `self:<channel>`."""
        groups.alone("a", "c1")
        self.assertEqual((groups.runs_under("self:c1"), groups.runs_under("b")), ("a", "b"))
        ran = []

        def run(argv, **kw):
            ran.append(argv[argv.index("insert") + 1])
            return subprocess.CompletedProcess(argv, 0, stdout='{"rows": [1]}', stderr="")
        with unittest.mock.patch.object(subprocess, "run", side_effect=run), \
                unittest.mock.patch.object(actions, "ENABLED", True):
            REAL_INSERT("self:c1", [])
            actions.record("self:c1", "c1", [{"type": "chat_sent", "payload": {}}], wait=True)
            naming.record("self:c1", "c1", "Alone")
        self.assertEqual(ran, ["a", "a", "a"])
        host = app_host.AppHost(0, write=lambda g, *rest: ran.append(g))
        self.addCleanup(host.close)
        host._write_one(("self:c1", {}, [{"type": "app_attached"}], []))
        self.assertEqual(ran[-1], "a")

    def sessions_here(self):
        started = sessions.Sessions()
        self.addCleanup(started.close)
        return started

    def test_an_actor_started_on_its_own_is_one_before_its_first_call(self):
        """Its record is in before ag's first of the conversation, which ag writes only when it has none: so its first
        call is built with its own context alone, and it is listed on its own from the start."""
        started = self.sessions_here()
        s = groups.start_alone(started, "b", self.tmp.name, "claude")
        sid = s["session_id"]
        self.assertEqual((s["gatherer"], s["cwd"], s["harness"]), ("self:" + sid, os.path.abspath(self.tmp.name), "claude"))
        [(via, [event])] = self.recorded                                   # one call to ag, as the group it runs under
        self.assertEqual((via, event["properties"]), ("b", {"channel": sid}))
        self.assertEqual(event["payload"], {"group": "self:" + sid, "under": "b", "name": "", "folder": None})
        self.assertNotIn("was", event["payload"])                          # from no group: told of no move
        self.assertEqual((self.members("self:" + sid), self.members("b")), ([sid], ["c2"]))
        self.assertEqual(groups.launch_group(sid, "self:" + sid), "b")    # ag runs it in the group it was started under
        listed = {g["name"]: (g.get("alone", False), sorted(a["channel"] for a in g["agents"]))
                  for g in data.home(started.list())["gatherers"]}
        self.assertEqual(listed["self:" + sid], (True, [sid]))
        self.assertEqual(listed["b"], (False, ["c2"]))

    def test_started_on_its_own_from_the_page_with_its_harness_and_permission_mode(self):
        """POST /api/sessions {alone: true}: the harness and permission mode the page names, each where it belongs."""
        import json
        import types
        from ag_dashboard.api import sessions as routes
        started = self.sessions_here()
        srv = types.SimpleNamespace(sessions=started)
        got = routes.start(srv, {"gatherer": "b", "cwd": self.tmp.name, "harness": "claude",
                                 "permission_mode": "acceptEdits", "model": "sonnet", "alone": True})
        self.assertEqual(got.status_code, 200)
        sid = json.loads(got.body)["session_id"]
        [row] = started.list()
        self.assertEqual((row["gatherer"], row["harness"], row["permission_mode"], row["model"]),
                         ("self:" + sid, "claude", "acceptEdits", "sonnet"))
        got = routes.start(srv, {"gatherer": "b", "cwd": self.tmp.name, "harness": "claude", "permission_mode": "plan"})
        row = next(r for r in started.list() if r["session_id"] == json.loads(got.body)["session_id"])
        self.assertEqual((row["gatherer"], row["harness"], row["permission_mode"]), ("b", "claude", "plan"))   # in a group too

    def test_a_coordinator_agent_over_everything_is_a_group_of_one_reading_every_group(self):
        from ag_dashboard import coordination
        started = self.sessions_here()
        crew = coordination.Coordination(started, watch=False)
        sid = crew.ensure("all", self.tmp.name, "claude")["session_id"]
        self.assertEqual((self.members("self:" + sid), self.members("a")), ([sid], ["c1", "c3"]))
        role = coordination._role_in("self:" + sid, sid)                   # in ag's database, before its first call
        self.assertEqual(role, {"role": "coordinator", "private": True, "over": "all", "reads": ["a", "b"]})
        self.recorded.clear()
        with unittest.mock.patch.object(actions, "record") as wrote:
            coordination.Coordination(started, watch=False)._mark_roles()     # a new dashboard: read, not written again
        wrote.assert_not_called()
        listed = {g["name"]: g for g in data.home(started.list())["gatherers"]}
        [a] = listed["self:" + sid]["agents"]
        self.assertEqual((a["role"], a["over"], listed["self:" + sid].get("alone")), ("coordinator", "all", True))
        self.assertEqual(crew.ensure("all")["session_id"], sid)                # one a node

    def test_listed_on_its_own_while_its_record_is_still_being_written(self):
        started = self.sessions_here()
        sid = started.create("a", self.tmp.name, harness="claude", alone=True)["session_id"]
        listed = {g["name"]: (g.get("alone", False), sorted(a["channel"] for a in g["agents"]))
                  for g in data.home(started.list())["gatherers"]}
        self.assertEqual(listed["self:" + sid], (True, [sid]))
        self.assertEqual(listed["a"], (False, ["c1", "c3"]))

    def test_forgotten_before_its_first_message_it_is_listed_nowhere(self):
        started = self.sessions_here()
        sid = groups.start_alone(started, "a", self.tmp.name, "claude")["session_id"]
        started.discard(sid)
        self.assertEqual(data.alone_names(), ["self:" + sid])              # its record stays: ag keeps every event
        self.assertNotIn("self:" + sid, [g["name"] for g in data.home(started.list())["gatherers"]])

    def test_not_started_on_its_own_when_ag_does_not_take_its_record(self):
        started = self.sessions_here()
        with unittest.mock.patch.object(actions, "insert", side_effect=RuntimeError("no")):
            with self.assertRaises(groups.GroupError):
                groups.start_alone(started, "a", self.tmp.name, "claude")
        self.assertEqual(started.list(), [])

    def test_not_started_on_its_own_on_a_harness_that_names_its_session_at_its_first_call(self):
        started = self.sessions_here()
        for harness in ("codex", "antigravity"):
            with self.assertRaisesRegex(groups.GroupError, "names its session only at its first call"):
                groups.start_alone(started, "a", self.tmp.name, harness)
        for under in ("nowhere", "self:c1"):
            with self.assertRaises(groups.GroupError):
                groups.start_alone(started, under, self.tmp.name, "claude")
        self.assertEqual((started.list(), self.recorded), ([], []))

    def test_refused_for_no_such_group_or_its_own(self):
        for to in ("a", "nowhere"):
            with self.assertRaises(groups.GroupError):
                groups.plan("a", to, ["c1"])

    def test_refused_with_a_database_per_gatherer(self):
        os.remove(paths.home_db())
        with self.assertRaises(groups.GroupError):
            groups.plan("a", "b", ["c1"])
        started = self.sessions_here()
        with self.assertRaises(groups.GroupError):
            groups.start_alone(started, "a", self.tmp.name, "claude")
        self.assertEqual(started.list(), [])
        with self.assertRaises(groups.GroupError):
            groups.merge("a", "b")

    # -- a folder made outside every group, and a group dropped into another

    def test_a_folder_made_outside_every_group_is_a_group_named_as_typed(self):
        shelf = gatherer_folders.make("Shelf")
        with unittest.mock.patch.object(groups.sessions, "new_gatherer", side_effect=self.made):
            self.assertEqual(groups.make("  Paper   figures "), {"group": "Paper_figures", "title": "Paper figures"})
            self.assertEqual(groups.make("b", shelf), {"group": "b_2", "title": "b"})    # in a folder of groups
            for bad, under in (("a/b", None), ("", None), ("x", 999)):
                with self.assertRaises(groups.GroupError):
                    groups.make(bad, under)
        self.assertEqual(titles.stored(), {"Paper_figures": "Paper figures", "b_2": "b"})
        self.assertEqual(gatherer_folders.stored()["filed"], {"b_2": shelf})
        self.assertEqual(data.gatherer_names(), ["Paper_figures", "a", "b", "b_2"])

    def test_a_group_dropped_into_another_is_a_folder_of_it_with_everything_in_it(self):
        work = folders.make("a", "Work")
        inner = folders.make("a", "Inner", work)
        folders.file("a", ["c3"], work)
        self.crew("k1", "a", f"folder:{work}")                    # over a folder of it: still over that folder
        self.crew("k2", "a", None)                                 # over the group: over the folder it becomes
        saved.choose("a", "c1", True)
        titles.give("a", "Group A")
        self.recorded.clear()
        got = groups.merge("a", "b")
        self.assertEqual(len(self.recorded), 1)                    # one call to ag
        fid = got["folder"]
        self.assertEqual((got["group"], got["name"], got["actors"]), ("b", "Group A", ["c1", "c3", "k1", "k2"]))
        self.assertEqual((self.members("a"), self.members("b")), ([], ["c1", "c2", "c3", "k1", "k2"]))
        tree = folders.of("b")
        self.assertEqual({f["name"]: f["parent"] for f in tree["folders"]}, {"Group A": None, "Work": fid, "Inner": work})
        self.assertIn(inner, {f["id"] for f in tree["folders"]})  # its folders keep their ids
        self.assertEqual(tree["filed"], {"c1": fid, "c3": work})   # at its top: in the new folder; else where it was
        self.assertEqual((self.over("k1"), self.over("k2")), (("b", f"folder:{work}"), ("b", f"folder:{fid}")))
        self.assertEqual(self.rows("saved"), [("b", "c1")])
        said = {e["properties"]["channel"]: e["payload"] for e in self.events("group") if e["payload"].get("was") == "a"}
        self.assertEqual((said["c1"]["group"], said["c1"]["was_name"]), ("b", "Group A"))
        self.assertIsNone(said["k2"]["folder"])                    # a coordinator agent is in no folder
        self.assertEqual(merges.stored(), {"a": "b"})
        self.assertEqual(data.gatherer_names(), ["b"])             # gone from the list, its directory kept
        self.assertEqual(data.gatherer_names(every=True), ["a", "b"])
        self.assertEqual(folders.of("a"), {"folders": [], "filed": {}})

    def test_a_merge_plan_changes_nothing_and_its_folder_takes_a_name_free_there(self):
        inbox = folders.make("b", "Inbox")
        folders.make("b", "A", inbox)
        folders.make("b", "a")
        got = groups.merge_plan("a", "b")
        self.assertEqual((got["folder"], got["actors"], got["before"]), ("a 2", 2, {"a": 2, "b": 1}))
        self.assertEqual(groups.merge_plan("a", "b", inbox)["folder"], "a 2")
        self.assertEqual(groups.merge_plan("a", "b", folders.make("b", "Other"))["folder"], "a")
        self.assertEqual((self.events("group"), self.members("a")), ([], ["c1", "c3"]))

    def test_an_actor_never_called_goes_too(self):
        conn = sqlite3.connect(sessions.db_path())
        try:
            with conn:
                conn.execute(sessions.SCHEMA)
                conn.execute("INSERT INTO sessions (session_id, gatherer, harness, cwd, permission_mode, created_at, "
                             "status) VALUES ('c9', 'a', 'claude', '/', 'auto', 'now', 'idle')")
        finally:
            conn.close()
        groups.merge("a", "b")
        self.assertIn("c9", self.members("b"))                     # its record in before its first call
        self.assertEqual(next(r["gatherer"] for r in sessions.stored() if r["session_id"] == "c9"), "b")

    def test_an_actor_on_its_own_that_left_a_merged_group_runs_under_the_group_it_went_into(self):
        groups.alone("a", "c1")
        groups.merge("a", "b")
        self.assertEqual(groups.launch_group("c1", "self:c1"), "b")

    def test_a_merge_refused_changes_nothing(self):
        saved.choose("a", "c1", True)
        for gatherer, to, into in (("a", "a", None), ("a", "nope", None), ("a", "b", 999)):
            with self.assertRaises(groups.GroupError):
                groups.merge(gatherer, to, into)
        groups.alone("a", "c3")
        for gatherer, to in (("self:c3", "b"), ("b", "self:c3")):
            with self.assertRaises(groups.GroupError):
                groups.merge(gatherer, to)
        with unittest.mock.patch.object(actions, "insert", side_effect=RuntimeError("no")):     # ag kept nothing
            with self.assertRaises(groups.GroupError):
                groups.merge("a", "b")
        self.assertEqual((self.members("a"), self.rows("saved"), merges.stored()), (["c1"], [("a", "c1")], {}))
        self.assertEqual(data.gatherer_names(), ["a", "b"])


    # ---- groups inside another group's folder (groups.py's `place`, `own`, `above`): the Notes design "Groups:
    # folders, defaults and Manage groups"

    def test_a_group_placed_in_another_s_folder_keeps_its_own_group(self):
        work = folders.make("a", "Work")
        shelf = gatherer_folders.make("Shelf")
        gatherer_folders.file(["b"], shelf)
        self.assertEqual(groups.place("b", "a", work), {"group": "b", "in": "a", "folder": work})
        self.assertEqual(groups.places(), {"b": {"in": "a", "folder": work}})
        self.assertEqual(data.home([])["places"], {"b": {"in": "a", "folder": work}})
        self.assertEqual((self.members("a"), self.members("b")), (["c1", "c3"], ["c2"]))   # no one shares anew
        self.assertEqual(gatherer_folders.stored()["filed"], {})                            # out of its folder of groups
        self.assertEqual(folders.of("a")["filed"], {})                                      # no actor of `a`'s
        groups.place("b", "a")                                                              # at `a`'s top
        self.assertEqual(groups.places(), {"b": {"in": "a", "folder": None}})
        groups.place("b", None)                                                             # back at the list's top
        self.assertEqual(groups.places(), {})

    def test_a_place_refused_changes_nothing(self):
        groups.place("b", "a")
        groups.alone("a", "c3")
        for gatherer, to, into in (("a", "b", None), ("a", "a", None), ("b", "nope", None), ("nope", "a", None),
                                   ("b", "a", 999), ("a", "self:c3", None)):
            with self.assertRaises(groups.GroupError):                                       # inside itself, ...
                groups.place(gatherer, to, into)
        self.assertEqual(groups.places(), {"b": {"in": "a", "folder": None}})

    def test_a_folder_given_its_own_group_stays_where_it_is_with_its_group_s_settings(self):
        work = folders.make("a", "Work")
        figures = folders.make("a", "Figures", work)
        folders.file("a", ["c3"], figures)
        with open(os.path.join(paths.TRACE_DIR, "a", "gatherer.toml"), "w") as fh:
            fh.write('# The gatherer a: its policy\npolicy = "proactive_context_manager"\npollers = []\n')
        with unittest.mock.patch.object(groups.sessions, "new_gatherer", side_effect=self.made):
            got = groups.own("a", figures)
        self.assertEqual((got["group"], got["actors"], got["in"], got["folder"]), ("Figures", ["c3"], "a", work))
        self.assertEqual((self.members("a"), self.members("Figures")), (["c1"], ["c3"]))
        self.assertEqual(groups.places(), {"Figures": {"in": "a", "folder": work}})
        with open(os.path.join(paths.TRACE_DIR, "Figures", "gatherer.toml")) as fh:
            self.assertEqual(fh.read(), '# The gatherer Figures: its policy\npolicy = "proactive_context_manager"\npollers = []\n')

    def test_a_group_placed_in_a_folder_goes_back_into_that_group_as_a_folder_there(self):
        work = folders.make("a", "Work")
        groups.place("b", "a", work)
        got = groups.above("b")
        self.assertEqual((got["group"], self.members("a"), self.members("b")), ("a", ["c1", "c2", "c3"], []))
        self.assertEqual(next(f for f in folders.of("a")["folders"] if f["id"] == got["folder"])["parent"], work)
        self.assertEqual(groups.places(), {})
        with self.assertRaises(groups.GroupError):                                           # placed nowhere
            groups.above("a")

    def test_an_actor_on_its_own_stays_in_its_folder_and_joins_its_group_again(self):
        work = folders.make("a", "Work")
        folders.file("a", ["c1"], work)
        got = groups.alone("a", "c1", here=True)
        self.assertEqual((got["group"], got["in"], got["folder"]), ("self:c1", "a", work))
        self.assertEqual((self.members("a"), self.members("self:c1")), (["c3"], ["c1"]))
        self.assertEqual(groups.places(), {"self:c1": {"in": "a", "folder": work}})
        groups.move("self:c1", "a", ["c1"], into=work)                                       # its folder's group again
        self.assertEqual((self.members("a"), folders.of("a")["filed"]), (["c1", "c3"], {"c1": work}))
        self.assertEqual(groups.places(), {})

    def test_a_group_inside_another_s_folder_is_under_that_folder_for_its_coordinator_agents(self):
        work = folders.make("a", "Work")
        groups.place("b", "a", work)
        groups.alone("a", "c3")
        tree = coordinators.Tree()
        self.assertEqual(tree.place("b", "c2"), ["all", "group:a", f"folder:{work}", "group:b"])
        self.assertEqual(coordinators.common([tree.place("a", "c1"), tree.place("b", "c2")]), ["all", "group:a"])
        self.assertEqual(tree.place("self:c3", "c3"), [])                     # on its own: under no coordinator agent
        actions.insert("a", [groups._placed("a", "b", None)])                 # a ring (`place` refuses one): each at its own place
        self.assertEqual(coordinators.Tree().place("b", "c2")[-1], "group:b")

    def test_a_group_placed_in_a_folder_goes_where_the_folder_goes(self):
        work = folders.make("a", "Work")
        inner = folders.make("a", "Inner", work)
        with unittest.mock.patch.object(groups.sessions, "new_gatherer", side_effect=self.made):
            self.made("x")
            groups.place("x", "a", inner)
            groups.move("a", "b", folder=work)                                               # its folder to `b`
            self.assertEqual(groups.places(), {"x": {"in": "b", "folder": inner}})
            groups.place("x", "b", work)
            got = groups.split("b", work)                                                    # its folder made a group
            self.assertEqual(groups.places(), {"x": {"in": got["group"], "folder": None}})
            groups.merge(got["group"], "a")                                                  # that group merged
            [merged] = [f for f in folders.of("a")["folders"] if f["name"] == "Work"]
            self.assertEqual(groups.places(), {"x": {"in": "a", "folder": merged["id"]}})


class GroupAdminTest(unittest.TestCase):
    """`ag groups` (group_admin.py): groups `a` (c1, c3) and `b` (c2), changed by name, each change said first --
    GroupsTest's home, without its tests."""

    setUp, insert, members, made = GroupsTest.setUp, GroupsTest.insert, GroupsTest.members, GroupsTest.made

    def ask(self, **body):
        return group_admin.manage(body)

    def test_the_list_says_where_each_group_and_actor_on_its_own_is(self):
        work = folders.make("a", "Work")
        titles.give("a", "Group A")
        groups.place("b", "a", work)
        folders.file("a", ["c1"], work)
        groups.alone("a", "c1", here=True)
        said = self.ask(op="list")["said"]
        self.assertIn("- Group A (a): 1 actor", said)
        self.assertIn("  - b (b), in Group A/Work: 1 actor, a group of its own", said)
        self.assertIn('  - c1 "c1 question 2", in Group A/Work: on its own', said)
        self.assertNotIn("- b (b): 1 actor", said)                              # not at the top as well
        shown = self.ask(op="show", group="Group A")["said"]
        self.assertIn("- inside Group A/Work: the group b (1 actor)", shown)

    def test_a_folder_given_its_own_group_by_its_path_said_first(self):
        work = folders.make("a", "Work")
        folders.file("a", ["c3"], work)
        got = self.ask(op="folder", path="a/work", to="own", dry_run=True)        # names: whatever their case
        self.assertFalse(got["done"])
        self.assertEqual(got["said"][1], "Its actor stops sharing context with the 1 other actor of a; it rebuilds its "
                                         "context at its next call.")
        self.assertEqual(self.members("a"), ["c1", "c3"])                         # nothing done
        with unittest.mock.patch.object(groups.sessions, "new_gatherer", side_effect=self.made):
            got = self.ask(op="folder", path="a/Work", to="own")
        self.assertTrue(got["done"])
        self.assertEqual((self.members("Work"), groups.places()), (["c3"], {"Work": {"in": "a", "folder": None}}))
        with self.assertRaises(groups.GroupError):                                # a group already
            self.ask(op="folder", path="a/Work", to="own")
        got = self.ask(op="folder", path="a/Work", to="parent")                    # its path goes through the group
        self.assertEqual((self.members("a"), groups.places()), (["c1", "c3"], {}))
        with self.assertRaises(groups.GroupError):                                # at the top: none above it
            self.ask(op="folder", path="b", to="parent")

    def test_an_actor_on_its_own_in_its_folder_and_back(self):
        work = folders.make("a", "Work")
        folders.file("a", ["c1"], work)
        self.ask(op="actor", actor="c1", to="alone")
        self.assertEqual(groups.places(), {"self:c1": {"in": "a", "folder": work}})
        with self.assertRaises(groups.GroupError):
            self.ask(op="actor", actor="c1", to="alone")
        self.ask(op="actor", actor="c1", to="folder")
        self.assertEqual((self.members("a"), folders.of("a")["filed"]), (["c1", "c3"], {"c1": work}))
        groups.alone("a", "c1")                                                   # at the list's top: no folder
        with self.assertRaises(groups.GroupError):
            self.ask(op="actor", actor="c1", to="folder")
        with self.assertRaises(groups.GroupError):                                # no such actor
            self.ask(op="actor", actor="zz", to="alone")

    def test_a_group_merged_or_kept_inside_another_s_folder_and_renamed(self):
        work = folders.make("a", "Work")
        self.assertIn("keeping its own group", self.ask(op="merge", group="b", into="a", folder="Work", keep=True)["said"][0])
        self.assertEqual(groups.places(), {"b": {"in": "a", "folder": work}})
        got = self.ask(op="merge", group="b", into="a", folder="Work", dry_run=True)
        self.assertIn("becomes a folder of a, named b, in a/Work", got["said"][0])
        self.assertEqual(self.members("b"), ["c2"])
        self.ask(op="merge", group="b", into="a")
        self.assertEqual(self.members("a"), ["c1", "c2", "c3"])
        self.ask(op="rename", group="a", title="Lab")
        self.assertEqual(titles.stored()["a"], "Lab")
        for bad in ({"op": "show", "group": "nope"}, {"op": "folder", "path": "a/Nope", "to": "own"}, {"op": "nope"}):
            with self.assertRaises(groups.GroupError):
                self.ask(**bad)


class GroupsCliTest(unittest.TestCase):
    """ag/cli/groups.py: what it asks the dashboard, and what it prints."""

    def run_cli(self, *argv, said=("It is said.",)):
        from ag.cli import actors as cli_actors, groups as cli
        out = []
        with unittest.mock.patch.object(cli_actors, "dashboard_url", return_value="http://d"), \
                unittest.mock.patch.object(cli_actors, "ask", return_value={"said": list(said)}) as ask, \
                unittest.mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(" ".join(map(str, a)))):
            code = cli.main(list(argv))
        return code, ask.call_args, out

    def test_each_command_asks_the_dashboard_and_prints_what_it_says(self):
        code, call, out = self.run_cli()
        self.assertEqual((code, call.args, call.kwargs, out), (0, ("http://d", "manage", {"op": "list", "dry_run": False}),
                                                               {"api": "groups"}, ["It is said."]))
        _, call, out = self.run_cli("--dry-run", "folder", "making_ag/Work", "own")
        self.assertEqual(call.args[2], {"op": "folder", "path": "making_ag/Work", "to": "own", "dry_run": True})
        self.assertEqual(out, ["It is said.", "Nothing changed (--dry-run)."])
        _, call, _ = self.run_cli("merge", "b", "a", "--folder", "Work", "--keep")
        self.assertEqual(call.args[2], {"op": "merge", "group": "b", "into": "a", "folder": "Work", "keep": True,
                                        "dry_run": False})
        _, call, _ = self.run_cli("actor", "c1", "alone", "--dry-run")
        self.assertTrue(call.args[2]["dry_run"])
        _, call, _ = self.run_cli("actor", "c1", "alone")
        self.assertEqual(call.args[2], {"op": "actor", "actor": "c1", "to": "alone", "dry_run": False})


class FoldersInHomeTest(GroupsTest):
    """The folder tree kept in the home's one database (folders.py), as `folder` and `group` records."""

    test_a_plan_says_who_moves_and_changes_nothing = test_a_move_is_one_call_to_ag = None     # GroupsTest's, run there
    test_an_actor_moved_is_in_its_new_group_with_its_rows = test_a_folder_moves_with_its_folders_and_every_actor_in_them = None
    test_a_task_moves_whole = test_nothing_of_the_dashboard_s_changes_when_ag_did_not_take_the_record = None
    test_a_folder_named_as_one_where_it_would_go_is_refused_before_anything = None
    test_refused_for_no_such_group_or_its_own = test_refused_with_a_database_per_gatherer = None
    test_a_folder_outside_every_group_is_a_group_of_its_own = test_a_new_group_s_name_is_one_no_group_has = None
    test_an_app_does_not_move_between_groups = None
    test_an_actor_on_its_own_is_a_group_of_one = test_an_actor_on_its_own_runs_under_the_group_it_left_and_comes_back = None
    test_an_actor_is_not_taken_out_with_others_of_its_task_nor_the_coordinator = None

    def kept_in_dashboard_db(self):
        if not os.path.exists(sessions.db_path()):
            return 0, 0
        conn = sqlite3.connect(sessions.db_path())
        try:
            if not folders._has(conn, "folders"):
                return 0, 0
            return tuple(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("folders", "filed"))
        finally:
            conn.close()

    def test_the_tree_is_kept_as_records_not_in_dashboard_db(self):
        work = folders.make("a", "Work")
        inner = folders.make("a", "Inner", work)
        folders.file("a", ["c1"], inner)
        folders.rename("a", work, "Jobs")
        self.assertEqual(folders.of("a"), {"folders": [{"id": inner, "parent": work, "name": "Inner", "closed": None},
                                                       {"id": work, "parent": None, "name": "Jobs", "closed": None}],
                                           "filed": {"c1": inner}})
        self.assertEqual(folders.of("b"), {"folders": [], "filed": {}})
        self.assertEqual(self.kept_in_dashboard_db(), (0, 0))
        self.assertEqual([e["payload"]["name"] for e in self.events("folder")], ["Work", "Inner", "Jobs"])

    def test_filing_an_actor_keeps_its_group(self):
        work = folders.make("a", "Work")
        folders.file("a", ["c1"], work)
        [event] = self.events("group")
        self.assertEqual(event["payload"], {"group": "a", "was": "a", "folder": work})   # no move: nothing rebuilt
        self.assertEqual(self.members("a"), ["c1", "c3"])
        folders.file("a", ["c1"], None)
        self.assertEqual(self.events("group")[-1]["payload"]["folder"], None)
        self.assertEqual(folders.of("a")["filed"], {})

    def test_a_folder_deleted_moves_its_actors_up_and_its_id_is_not_used_again(self):
        work = folders.make("a", "Work")
        inner = folders.make("a", "Inner", work)
        folders.file("a", ["c1"], inner)
        folders.delete("a", inner)
        self.assertEqual(folders.of("a"), {"folders": [{"id": work, "parent": None, "name": "Work", "closed": None}],
                                           "filed": {"c1": work}})
        self.assertGreater(folders.make("a", "Next"), inner)

    def test_an_app_in_a_folder_is_no_conversation(self):
        work = folders.make("a", "Work")
        folders.file("a", ["app:x1"], work)
        self.assertEqual(folders.of("a")["filed"], {"app:x1": work})
        self.assertEqual(self.members("a"), ["c1", "c3"])                 # not one of the group's channels
        self.assertEqual([e["payload"] for e in self.events("filed")], [{"item": "app:x1", "group": "a", "folder": work}])
        self.assertNotIn("properties", self.events("filed")[0])
        folders.file("a", ["app:x1"], None)
        self.assertEqual(folders.of("a")["filed"], {})

    def test_a_folder_closed_and_reopened(self):
        work = folders.make("a", "Work")
        folders.mark("a", work, True)
        self.assertIsNotNone(folders.of("a")["folders"][0]["closed"])
        folders.reopen("a", work)
        self.assertIsNone(folders.of("a")["folders"][0]["closed"])

    def test_nothing_is_kept_when_ag_does_not_take_a_change(self):
        work = folders.make("a", "Work")
        with unittest.mock.patch.object(actions, "insert", side_effect=RuntimeError("no")):
            with self.assertRaises(folders.FolderError):
                folders.rename("a", work, "Jobs")
            with self.assertRaises(folders.FolderError):
                folders.make("a", "Other")
        self.assertEqual([f["name"] for f in folders.of("a")["folders"]], ["Work"])

    def test_dashboard_db_s_folders_come_in_once(self):
        with unittest.mock.patch.object(folders.sessions.home, "merged", return_value=False):    # before the merge
            work = folders.make("a", "Work")
            other = folders.make("b", "Other")
            folders.file("a", ["c1"], work)
            folders.file("b", ["c2"], other)
            folders.file("a", ["c3"], work)
        insert(self.m, "b", {}, [{"type": "group", "id": "group:c3:moved", "properties": {"channel": "c3"},
                                  "payload": {"group": "b", "was": "a"}}])          # moved to b since: left as it is
        self.assertEqual(folders.of("a"), {"folders": [{"id": work, "parent": None, "name": "Work", "closed": None}],
                                           "filed": {"c1": work}})
        self.assertEqual(folders.of("b")["filed"], {"c2": other})
        self.assertEqual(self.kept_in_dashboard_db(), (2, 3))                     # left as they were
        copied = len(self.recorded)
        folders._copied.clear()
        folders.stored()
        self.assertEqual(len(self.recorded), copied)                                # once


class GroupAppsTest(GroupsTest):
    """Apps of a task or a folder that moves: `pages` (many instances) goes with it, `board` (one per group) stays;
    `news` (one per group too) goes with its own agent, an actor it started."""

    def setUp(self):
        super().setUp()
        src = os.path.join(self.tmp.name, "apps-src")
        for name, mode in (("pages", "many"), ("board", "one"), ("news", "one")):
            write_app(src, name, NOTES.replace("notes", name).replace('instances = "per-folder"', f'instances = "{mode}"'))
        for patch in (unittest.mock.patch.dict(os.environ, {app_host.PATH_ENV: src}),
                      unittest.mock.patch.object(app_kit.finding, "BUILTIN", os.path.join(self.tmp.name, "no-apps"))):
            patch.start()
            self.addCleanup(patch.stop)
        self.host = app_host.AppHost(0, write=insert_here)
        self.addCleanup(self.host.close)
        placed = unittest.mock.patch.object(tool_gateway, "HOST", self.host)
        placed.start()
        self.addCleanup(placed.stop)
        self.folder = tempfile.mkdtemp(dir=self.tmp.name)

    def test_a_group_read_first_after_a_change_has_it_though_its_record_is_still_being_written(self):
        """In the one database a group's first read (`_load`) reads every group's app records: what the host let go of
        just before -- an agent detached, an instance closed -- whose record its writer has not written yet, stays let
        go (each write slowed here: on a slow machine, as on CI, the read came first and brought them back)."""
        host = app_host.AppHost(0, write=lambda *a: (time.sleep(0.2), insert_here(*a)))
        self.addCleanup(host.close)
        page = host.open("pages", "a", self.folder)
        shut = host.open("pages", "a", self.folder)
        for c in ("c1", "c3"):
            host.attach("a", page.id, c)
        host.flush()
        host.detach("a", page.id, "c3")
        host.close_instance("a", shut.id)
        self.assertEqual(host.instances_of("b"), [])                                  # b's first read: every record
        self.assertEqual(host.agents_of(host.instance("a", page.id)), ["c1"])
        self.assertEqual([i.id for i in host.instances_of("a")], [page.id])

    def test_an_app_of_a_task_that_moves_goes_with_it_and_its_actors_keep_it(self):
        page = self.host.open("pages", "a", self.folder)
        for c in ("c1", "c3"):
            self.host.attach("a", page.id, c)                             # c3: using it, in no task with it
        tasks.add("a", "c1", ["app:" + page.id])
        work = folders.make("a", "Work")
        folders.file("a", ["c1", "app:" + page.id], work)
        plan = groups.plan("a", "b", ["c1"])
        self.assertEqual((plan["actors"], [x["id"] for x in plan["apps"]]), (["c1"], [page.id]))
        self.assertEqual(groups.move("a", "b", folder=work)["apps"], [page.id])
        self.assertEqual([i.id for i in self.host.instances_of("b")], [page.id])     # listed and reached in b
        self.assertEqual(self.host.instances_of("a"), [])
        self.assertEqual([i.id for i in self.host.attached_to("b", "c1")], [page.id])
        self.assertEqual(self.host.agents_of(self.host.instance("b", page.id)), ["c1"])   # c3, staying, let go
        self.assertEqual(folders.of("b")["filed"].get("app:" + page.id), work)        # still in its folder
        self.assertEqual(tasks.stored()["b"]["tasked"]["app:" + page.id], tasks.stored()["b"]["tasked"]["c1"])
        self.host.flush()
        again = app_host.AppHost(0, write=insert_here)                    # read back from the one database
        self.addCleanup(again.close)
        self.assertEqual([i.id for i in again.instances_of("b")], [page.id])
        self.assertEqual(again.agents_of(again.instance("b", page.id)), ["c1"])

    def test_a_group_s_only_one_of_an_app_stays_and_a_move_taking_it_is_refused(self):
        board = self.host.open("board", "a", self.folder)
        tasks.add("a", "c1", ["app:" + board.id])
        with self.assertRaisesRegex(groups.GroupError, "the group's only one"):
            groups.plan("a", "b", ["c1"])
        with self.assertRaises(groups.GroupError):
            groups.move("a", "b", ["c1"])
        self.assertEqual((self.members("a"), [i.id for i in self.host.instances_of("a")]), (["c1", "c3"], [board.id]))

    def test_an_actor_that_moves_or_goes_alone_lets_go_of_the_apps_that_stay(self):
        page = self.host.open("pages", "a", self.folder)
        for c in ("c1", "c3"):
            self.host.attach("a", page.id, c)
        groups.move("a", "b", ["c1"])
        self.assertEqual(self.host.agents_of(page), ["c3"])
        self.assertEqual(self.host.attached_to("b", "c1"), [])
        groups.alone("a", "c3")
        self.assertEqual(self.host.agents_of(page), [])
        self.assertEqual([i.id for i in self.host.instances_of("a")], [page.id])     # the app stays where it was

    def started(self, channel, gatherer, inst):
        """`channel`, of `gatherer`, made the agent the app of `inst` started: its role names it, and it is attached."""
        conn = sqlite3.connect(sessions.db_path())
        try:
            with conn:
                conn.execute(sessions.SCHEMA)
                conn.execute("INSERT INTO sessions (session_id, gatherer, harness, cwd, permission_mode, created_at, "
                             "status, role) VALUES (?, ?, 'claude', '/', 'auto', 'now', 'idle', ?)",
                             (channel, gatherer, app_agents.role(inst.app, inst.id)))
        finally:
            conn.close()
        self.host.attach(gatherer, inst.id, channel)

    def role(self, channel):
        return next(app_agents.role_of(s) for s in sessions.stored() if s["session_id"] == channel)

    def test_an_app_s_own_agent_and_its_window_go_together_whichever_is_dragged(self):
        news = self.host.open("news", "a", self.folder)
        self.started("c1", "a", news)                                     # in no task with it
        for dragged in (["c1"], ["app:" + news.id]):
            plan = groups.plan("a", "b", dragged)
            self.assertEqual((plan["actors"], [x["id"] for x in plan["apps"]]), (["c1"], [news.id]))
            self.assertNotIn("joins", plan["apps"][0])                    # b has no news of its own
        board = self.host.open("board", "a", self.folder)                # one per group, with no agent of its own
        with self.assertRaisesRegex(groups.GroupError, "the group's only one"):
            groups.plan("a", "b", ["app:" + board.id])
        got = groups.move("a", "b", ["app:" + news.id])
        self.assertEqual((got["actors"], got["apps"], got["joined"]), (["c1"], [news.id], {}))
        self.assertEqual([i.id for i in self.host.instances_of("b")], [news.id])
        self.assertEqual(self.host.agents_of(self.host.instance("b", news.id)), ["c1"])
        self.assertEqual([i.id for i in self.host.instances_of("a")], [board.id])

    def test_into_a_group_with_its_own_one_the_window_closes_and_its_agent_works_with_that_one(self):
        news, theirs = self.host.open("news", "a", self.folder), self.host.open("news", "b", self.folder)
        self.started("c1", "a", news)
        tasks.add("a", "c1", ["app:" + news.id])
        [said] = groups.plan("a", "b", ["c1"])["apps"]
        self.assertEqual(said["joins"]["id"], theirs.id)
        got = groups.move("a", "b", ["c1"])
        self.assertEqual((got["apps"], got["joined"]), ([], {news.id: theirs.id}))
        self.assertEqual(self.host.instances_of("a"), [])                # closed: b's is the one
        self.assertEqual([i.id for i in self.host.instances_of("b")], [theirs.id])
        self.assertEqual(self.host.agents_of(theirs), ["c1"])
        self.assertEqual(self.role("c1"), ("news", theirs.id))           # not the closed one, made again at a start
        b = tasks.stored()["b"]["tasked"]
        self.assertEqual(b["c1"], b["app:" + theirs.id])
        self.assertNotIn("app:" + news.id, {**tasks.stored().get("a", {}).get("tasked", {}), **b})
        self.host.flush()
        again = app_host.AppHost(0, write=insert_here)                    # read back from the one database
        self.addCleanup(again.close)
        self.assertEqual([i.id for i in again.instances_of("b")], [theirs.id])
        self.assertEqual(again.agents_of(again.instance("b", theirs.id)), ["c1"])

    def test_an_app_s_agent_goes_on_its_own_with_its_window_and_its_task_s_apps_and_comes_back(self):
        news, page = self.host.open("news", "a", self.folder), self.host.open("pages", "a", self.folder)
        self.started("c1", "a", news)
        tasks.add("a", "c1", ["app:" + page.id])
        self.host.attach("a", page.id, "c1")
        got = groups.alone("a", "c1")
        self.assertEqual((got["group"], got["actors"], sorted(got["apps"])), ("self:c1", ["c1"], sorted([news.id, page.id])))
        self.assertEqual(sorted(i.id for i in self.host.instances_of("self:c1")), sorted([news.id, page.id]))
        self.assertEqual(self.host.agents_of(news), ["c1"])
        self.assertEqual(self.host.instances_of("a"), [])
        self.assertEqual(tasks.stored()["self:c1"]["tasked"]["app:" + page.id], tasks.stored()["self:c1"]["tasked"]["c1"])
        self.host.flush()                                                 # its records written as the group it left:
        self.assertEqual(sorted(os.listdir(paths.TRACE_DIR)), ["a", "b"])  # no gatherer made for its group of one
        groups.move("self:c1", "b", ["c1"])
        self.assertEqual(sorted(i.id for i in self.host.instances_of("b")), sorted([news.id, page.id]))
        self.assertEqual(data.alone_names(), [])

    def test_an_app_s_notifications_are_listed_in_the_group_it_moved_to(self):
        """The home lists an instance's open notifications under the group the host lists it in (`app_notices`), not
        the one it was opened in: moved on its own with its agent, then into another group, they go with it."""
        news = self.host.open("news", "a", self.folder)
        self.started("c1", "a", news)
        self.host._record(news, "app_notified", app_kit.notices.made("Build finished"))

        def listed(group):
            self.host.flush()
            conn = data._connect(group)
            try:
                return list(data.app_notices(conn, group))
            finally:
                conn.close()

        self.assertEqual(listed("a"), [news.id])
        groups.alone("a", "c1")
        self.assertEqual((listed("a"), listed("self:c1")), ([], [news.id]))
        groups.move("self:c1", "b", ["c1"])
        self.assertEqual((listed("self:c1"), listed("b")), ([], [news.id]))

    def test_an_actor_on_its_own_is_not_one_with_an_actor_in_its_task_nor_a_window_it_can_t_take(self):
        board = self.host.open("board", "a", self.folder)
        tasks.add("a", "c1", ["app:" + board.id])
        with self.assertRaisesRegex(groups.GroupError, "the group's only one"):
            groups.alone("a", "c1")
        self.assertEqual((self.members("a"), [i.id for i in self.host.instances_of("a")]), (["c1", "c3"], [board.id]))


    def test_a_group_merged_brings_every_app_and_what_each_keeps_for_it(self):
        """A many-instance app goes, into the folder its group becomes; a group's only one of its app goes into a group
        that has none, and closes for the one of a group that has, its agents working with that one; each told to carry
        over what it keeps for the group (`folded`)."""
        page, board, news = (self.host.open(app, "a", self.folder) for app in ("pages", "board", "news"))
        theirs = self.host.open("news", "b", self.folder)
        self.started("c1", "a", news)
        work = folders.make("a", "Work")
        folders.file("a", ["app:" + page.id], work)
        plan = groups.merge_plan("a", "b")
        self.assertEqual({x["id"]: x.get("joins", {}).get("id") for x in plan["apps"]},
                         {page.id: None, board.id: None, news.id: theirs.id})
        with unittest.mock.patch.object(self.host, "folded") as folded:
            got = groups.merge("a", "b")
        self.assertEqual((sorted(got["apps"]), got["joined"]), (sorted([page.id, board.id]), {news.id: theirs.id}))
        self.assertEqual(sorted(i.id for i in self.host.instances_of("b")), sorted([page.id, board.id, theirs.id]))
        self.assertEqual(self.host.instances_of("a"), [])
        self.assertEqual(self.host.agents_of(theirs), ["c1"])
        self.assertEqual(self.role("c1"), ("news", theirs.id))
        filed = folders.of("b")["filed"]
        self.assertEqual((filed.get("app:" + page.id), filed.get("app:" + board.id)), (work, got["folder"]))
        self.assertEqual(sorted((c.args[0], c.args[1].id, c.args[2]) for c in folded.call_args_list),
                         sorted([("a", page.id, "a"), ("a", board.id, "a"), ("a", theirs.id, "a")]))


if __name__ == "__main__":
    unittest.main()
