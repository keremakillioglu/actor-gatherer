"""The dashboard as the apps' host (app_host.py, api/apps.py; app_kit/DESIGN.md step 2): apps found by their manifests,
their instances and agents kept as ag events, what an app inserts and reads checked against its manifest, its events
reaching an agent's context through ag's own policy unchanged, and each app's own origin."""
import contextlib
import gc
import http.client
import io
import json
import os
import queue
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import unittest.mock
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ag.ag_harness.home.__main__ as home_module  # noqa: E402
from ag.ag_harness.home.__main__ import main as home_main  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.cli import apps as apps_cli  # noqa: E402
from ag_dashboard import access, app_host, data, server, task_links, tasks, tool_gateway  # noqa: E402
import app_kit  # noqa: E402
from app_kit import AppError, Caller  # noqa: E402
from channels import ch  # noqa: E402
from test_dashboard import HomeBase  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NOTES = """
name = "notes"
label = "Notes"
version = "1"
instances = "per-folder"
access = "group"
instructions = "Keep notes with notes_add."

[backend]
python = "backend:NotesApp"

[panel]
entry = "panel/index.html"

[[tools]]
name = "add"
description = "Add a note."
input_schema = { type = "object", properties = { text = { type = "string" } }, required = ["text"] }

[[tools]]
name = "picked"
description = "What the user picked in the panel."
handled_by = "panel"

[[events]]
name = "notes.added"
properties = ["by"]

[capabilities]
reads = ["user_message"]
"""

BACKEND = '''
from app_kit import App, AppError, Response, ToolResult


class NotesApp(App):
    def open(self, instance, args):
        return type(instance)(**{**instance.to_dict(), "title": args.get("title", "Notes"), "data": {"opened": 1}})

    def call(self, instance, tool, args, caller):
        if tool == "add":
            self.host.insert(instance, [{"type": "notes.added", "payload": {"text": args["text"]},
                                         "properties": {"by": caller.channel or "user"}}], channel=caller.channel)
            return ToolResult.text("kept")
        raise AppError("no such tool")

    def attached(self, instance, channel):
        self.host.tell_panel(instance, {"hello": channel})

    def sleep(self, instance):
        self.slept = getattr(self, "slept", []) + [instance.id]

    def request(self, instance, method, path, query, body):
        if path == "count":
            return Response.json({"n": len(self.host.read(instance, ["notes.added"])), "method": method})
        return Response(404, b"none")
'''


BOOK = BACKEND.replace('"properties": {"by": caller.channel or "user"}}], channel=caller.channel)',
                       '"properties": {"by": caller.channel or "user"}}])'   # nothing in the caller's channel
                       ).replace("notes.added", "book.added")
assert BOOK != BACKEND


def book_toml(instances: str, access: str = "group") -> str:
    """The test app as "book": its own events' names, `instances` and `access` its."""
    return (NOTES.replace('name = "notes"', 'name = "book"').replace('label = "Notes"', 'label = "Book"')
            .replace("notes.added", "book.added")
            .replace('instances = "per-folder"\naccess = "group"', f'instances = "{instances}"\naccess = "{access}"'))


def write_app(root: str, name: str, toml: str, backend: str = BACKEND) -> str:
    folder = os.path.join(root, name)
    os.makedirs(os.path.join(folder, "panel"), exist_ok=True)
    with open(os.path.join(folder, "app.toml"), "w") as fh:
        fh.write(toml)
    with open(os.path.join(folder, "backend.py"), "w") as fh:
        fh.write(backend)
    with open(os.path.join(folder, "panel", "index.html"), "w") as fh:
        fh.write("<!doctype html><title>Notes</title>")
    return folder


_INSERTING = threading.Lock()


def insert_here(gatherer, properties, events, types):
    """What `ag home insert` does, run here: ag's own code, on the test's home -- what it prints kept from its module's
    `print` alone (redirect_stdout would take every thread's output: a test's own, printed meanwhile). Never outside a
    temporary folder: a host's write landing after a test put the home back (its tearDown run, the write still queued)
    would otherwise go to the real home -- dropped instead."""
    home = os.path.realpath(paths.AG_HOME or "")
    if not home.startswith(os.path.realpath(tempfile.gettempdir()) + os.sep):
        return
    said = []
    with _INSERTING, unittest.mock.patch.object(home_module, "print", create=True,
                                                new=lambda *a, **k: said.append(" ".join(map(str, a)))):
        try:
            code = home_main(["insert", gatherer, "--properties", json.dumps(properties), "--types",
                              json.dumps(types), "--events", json.dumps(events)])
        finally:
            with warnings.catch_warnings():               # the command's database, which it leaves to its process's
                warnings.simplefilter("ignore", ResourceWarning)   # end: let go here, not in another test's middle
                gc.collect()
    if code:
        raise RuntimeError("\n".join(said))


class HostBase(HomeBase):
    def setUp(self):
        super().setUp()
        self.apps_dir = os.path.join(self.tmp.name, "apps-src")
        write_app(self.apps_dir, "notes", NOTES)
        env = unittest.mock.patch.dict(os.environ, {app_host.PATH_ENV: self.apps_dir})
        env.start()
        self.addCleanup(env.stop)
        builtin = unittest.mock.patch.object(app_kit.finding, "BUILTIN", os.path.join(self.tmp.name, "no-apps"))
        builtin.start()                             # the test's apps alone: not the ones ag comes with (ag_apps/)
        self.addCleanup(builtin.stop)
        self.host = self.new_host()
        self.folder = tempfile.mkdtemp(dir=self.tmp.name)

    def new_host(self) -> "app_host.AppHost":
        h = app_host.AppHost(0, write=insert_here)
        self.addCleanup(h.close)
        self.hosts.append(h)                        # closed before the home goes (HomeBase's tearDown)
        return h

    def rows(self, sql, *args):
        conn = self.m._conn("g")
        return conn.execute(sql, args).fetchall()


class FindTest(HostBase):
    def test_apps_are_found_by_their_manifests_and_a_broken_one_says_why(self):
        write_app(self.apps_dir, "bad", NOTES.replace('name = "notes"', 'name = "Bad"'))
        self.host.find()
        got = self.host.listed()
        self.assertEqual([a["name"] for a in got["apps"]], ["notes"])
        self.assertEqual(got["apps"][0]["origin"], "http://notes.localhost:0")
        self.assertIn("name: 'Bad'", got["broken"][0]["error"])

    def test_an_app_s_name_is_a_host_name_s_label(self):
        self.assertEqual(app_host.origin_label("my_notes"), "my-notes")


class InstancesTest(HostBase):
    def test_one_instance_per_folder_kept_as_events_and_read_back_by_a_new_host(self):
        a = self.host.open("notes", "g", self.folder, {"title": "Mine"})
        self.assertEqual((a.title, a.data, a.folder), ("Mine", {"opened": 1}, os.path.realpath(self.folder)))
        self.assertEqual(self.host.open("notes", "g", self.folder).id, a.id)        # the open one
        b = self.host.open("notes", "g", tempfile.mkdtemp(dir=self.tmp.name))
        self.assertNotEqual(a.id, b.id)
        self.host.attach("g", a.id, "c1")
        self.host.attach("g", a.id, "c2")
        self.host.detach("g", a.id, "c2")
        self.host.close_instance("g", b.id)
        self.host.flush()
        again = self.new_host()                                                    # memory gone: the records stay
        got = again.listed("g")
        self.assertEqual([i["id"] for i in got["instances"]], [a.id])
        self.assertEqual(got["attached"], {a.id: ["c1"]})
        self.assertEqual(again.instance("g", a.id).title, "Mine")
        kinds = [r[0] for r in self.rows("SELECT t.name FROM events e JOIN event_types t USING (event_type_id) "
                                         "WHERE t.name LIKE 'app_%' ORDER BY e.row_id")]
        self.assertEqual(kinds, ["app_opened", "app_opened", "app_attached", "app_attached", "app_detached",
                                 "app_closed"])

    def test_an_instance_named_by_the_user_is_kept_over_its_title_and_read_back(self):
        a = self.host.open("notes", "g", self.folder, {"title": "Mine"})
        sub, leave = self.host.subscribe("notes", a, [])
        self.addCleanup(leave)
        got = self.host.rename("g", a.id, "  Trip   plans ")
        self.assertEqual((got.name, got.title), ("Trip plans", "Mine"))           # the app's title kept under it
        self.assertEqual(sub.queue.get(timeout=5), ("message", {"ag": "instance", "attached": [], "name": "Trip plans"}))
        self.assertEqual(self.host.listed("g")["instances"][0]["name"], "Trip plans")
        self.assertEqual(self.host.rename("g", a.id, "Trip plans").name, "Trip plans")   # the same: nothing kept
        self.assertEqual(len(self.host.rename("g", a.id, "x" * 300).name), app_host.NAME_CHARS)
        self.host.flush()
        self.assertEqual(self.new_host().instance("g", a.id).name, "x" * app_host.NAME_CHARS)   # read back
        self.host.rename("g", a.id, "  ")                                         # none: its title again
        self.host.flush()
        self.assertEqual(self.new_host().instance("g", a.id).name, "")
        named = [json.loads(r[0]) for r in self.rows(
            "SELECT payload_json FROM events WHERE event_type_id = "
            "(SELECT event_type_id FROM event_types WHERE name = 'app_named') ORDER BY row_id")]
        self.assertEqual([(n["name"][:10], n["by"]) for n in named],
                         [("Trip plans", "user"), ("xxxxxxxxxx", "user"), ("", "user")])
        with self.assertRaises(AppError):
            self.host.rename("g", "nope", "x")

    def test_an_instance_put_to_sleep_stays_open_its_agents_attached(self):
        a = self.host.open("notes", "g", self.folder)
        self.host.attach("g", a.id, "c1")
        self.host.sleep_instance("g", a.id)                                        # its task closed
        self.assertEqual(self.host.backend("notes").slept, [a.id])                 # its backend let go of it
        got = self.host.listed("g")
        self.assertEqual(([i["id"] for i in got["instances"]], got["attached"]), ([a.id], {a.id: ["c1"]}))
        with self.assertRaises(AppError):
            self.host.sleep_instance("g", "nope")

    def test_an_attachment_is_in_the_agent_s_channel_and_no_conversation_view_shows_it(self):
        a = self.host.open("notes", "g", self.folder)
        self.host.attach("g", a.id, "c1")
        self.host.flush()
        self.assertEqual(self.rows("SELECT p_channel, p_app, p_instance FROM events WHERE event_type_id = "
                                   "(SELECT event_type_id FROM event_types WHERE name = 'app_attached')"),
                         [("c1", "notes", a.id)])
        shown = self.rows(f"SELECT count(*) FROM events e WHERE e.p_channel = 'c1' AND {data.NOT_RECORD} AND "
                          f"e.row_id > (SELECT max(row_id) - 1 FROM events)")
        self.assertEqual(shown[0][0], 0)

    def test_the_app_s_types_are_declared_to_ag_as_its_manifest_says(self):
        a = self.host.open("notes", "g", self.folder)
        self.host.attach("g", a.id, "c1")
        self.host.call("notes", a, "add", {"text": "x"}, Caller(channel="c1", gatherer="g"))
        self.host.flush()
        props = {n: (r, i) for n, r, i in self.rows(
            "SELECT p.name, p.required, p.identifies FROM event_type_properties p JOIN event_types t "
            "USING (event_type_id) WHERE t.name = 'notes.added'")}
        self.assertEqual(set(props), {"app", "instance", "channel", "by"})
        self.assertEqual(props["app"], (1, 0))


class EventsTest(HostBase):
    def setUp(self):
        super().setUp()
        self.i = self.host.open("notes", "g", self.folder)
        self.host.attach("g", self.i.id, "c1")

    def refused(self, events, says, channel=None):
        with self.assertRaises(AppError) as ctx:
            self.host.insert("notes", self.i, events, channel)
        self.assertIn(says, str(ctx.exception))

    def test_what_an_app_may_not_insert(self):
        self.refused([{"type": "notes.removed", "payload": {}}], "not an event type notes may insert")
        self.refused([{"type": "user_message", "payload": {}}], "not an event type notes may insert")
        self.refused([{"type": "app_attached", "payload": {}}], "not an event type notes may insert")
        self.refused([{"type": "context_stream", "payload": {"stream": "Notes"}}], "author, text must be text")
        self.refused([{"type": "environment_update", "payload": {"what": "changed"}}], "subject must be text")
        self.refused([{"type": "notes.added", "payload": {}, "properties": {"channel": "c2"}}], "the host's")
        self.refused([{"type": "notes.added", "payload": {}, "properties": {"colour": "red"}}], "declares no property")
        self.refused([{"type": "notes.added", "payload": {}}], "not an agent that may use", channel="c2")
        self.refused([], "a list")

    def test_its_events_carry_the_host_s_properties_and_only_its_instance_reads_them(self):
        self.host.insert("notes", self.i, [{"type": "notes.added", "id": "n1", "payload": {"text": "a"},
                                            "properties": {"by": "user"}}], channel="c1")
        self.host.insert("notes", self.i, [{"type": "notes.added", "id": "n1", "payload": {"text": "again"}}],
                         channel="c1")
        self.host.flush()
        got = self.host.read("notes", self.i, ["notes.added"])
        self.assertEqual(len(got), 1)                                     # its id: the same event, stored once
        self.assertEqual(got[0]["properties"], {"app": "notes", "instance": self.i.id, "channel": "c1", "by": "user"})
        other = self.host.open("notes", "g", tempfile.mkdtemp(dir=self.tmp.name))
        self.assertEqual(self.host.read("notes", other, ["notes.added"]), [])
        self.assertEqual([e["type"] for e in self.host.read("notes", self.i, ["app_opened", "app_attached"])],
                         ["app_opened", "app_attached"])

    def test_what_it_reads_of_the_gatherer_is_what_its_manifest_names_of_its_agents_only(self):
        with self.assertRaises(AppError):
            self.host.read("notes", self.i, ["tool_call"])                # not named in its capabilities
        mine = self.host.read("notes", self.i, ["user_message"])
        self.assertTrue(mine)
        self.assertEqual({e["properties"]["channel"] for e in mine}, {"c1"})   # c1's: not c2's
        self.host.detach("g", self.i.id, "c1")
        self.assertEqual(self.host.read("notes", self.i, ["user_message"]), [])

    def test_a_context_stream_reaches_the_attached_agent_through_ag_s_own_policy(self):
        """ag's context management unchanged: the app's message is a context_stream, which the policy shows the
        agent whose channel it is in -- and not another agent."""
        self.host.insert("notes", self.i, [app_kit.context_stream("Notes", "the user", "pinned: buy milk",
                                                                  timestamp=1700000000)], channel="c1")
        self.host.flush()
        ctx_c1, _ = self.m._context("g", store.high_water(self.m._conn("g")), ch("c1"), 244800)
        ctx_c2, _ = self.m._context("g", store.high_water(self.m._conn("g")), ch("c2"), 244800)
        shown = [i["text"] for i in ctx_c1.items if i.get("name") == "context_stream"]
        self.assertEqual(len(shown), 1)
        self.assertIn(f"Message in Notes ({self.i.id}) from the user at", shown[0])   # the policy's own wording,
                                                                                    # the instance named
        self.assertIn("pinned: buy milk", shown[0])
        self.assertNotIn("buy milk", json.dumps(ctx_c2.items))
        self.assertEqual([e["text"] for e in self.host.read("notes", self.i, ["context_stream"])],
                         ["the user in Notes: pinned: buy milk"])


class HeldWritesTest(HostBase):
    """A gatherer with no database yet (a new one, before its first agent's first call): its writes held, in order,
    and written once its database is there -- holding up neither a flush nor another gatherer's writes."""

    def test_a_new_gatherer_s_writes_wait_for_its_database_and_hold_up_nothing(self):
        written, made = [], set()

        def write(gatherer, properties, events, types):
            if gatherer not in made:
                raise RuntimeError(f"{{\"error\": \"no database for gatherer '{gatherer}'\"}}")
            written.append((gatherer, events[0]["payload"]["n"]))

        made.add("old")
        h = app_host.AppHost(0, write=write)
        self.addCleanup(h.close)
        ev = lambda n: [{"type": "x", "payload": {"n": n}}]   # noqa: E731
        h._write("new", {}, ev(1), [])
        h._write("new", {}, ev(2), [])
        h._write("old", {}, ev(3), [])
        begun = time.time()
        h.flush()
        self.assertLess(time.time() - begun, 1.0)              # not held up by the new gatherer's
        self.assertEqual(written, [("old", 3)])
        made.add("new")
        db = app_host.home.db_path("new")
        os.makedirs(os.path.dirname(db), exist_ok=True)
        open(db, "w").close()                                  # its database, there now
        end = time.time() + 10
        while len(written) < 3 and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(written, [("old", 3), ("new", 1), ("new", 2)])   # in order, once it is there


class CallsTest(HostBase):
    def setUp(self):
        super().setUp()
        self.i = self.host.open("notes", "g", self.folder)
        self.host.attach("g", self.i.id, "c1")

    def test_a_tool_call_goes_to_the_backend_and_is_kept(self):
        got = self.host.call("notes", self.i, "add", {"text": "milk"}, Caller(channel="c1", gatherer="g"))
        self.assertEqual(got.to_dict(), {"content": [{"type": "text", "text": "kept"}], "isError": False})
        self.host.flush()
        self.assertEqual([(e["properties"]["channel"], e["payload"]) for e in
                          self.host.read("notes", self.i, ["notes.added"])], [("c1", {"text": "milk"})])
        calls = self.host.read("notes", self.i, ["app_call"])
        self.assertEqual((calls[0]["payload"]["tool"], calls[0]["payload"]["ok"]), ("add", True))

    def test_what_a_call_is_refused(self):
        self.assertTrue(self.host.call("notes", self.i, "nope", {}, Caller(channel="c1")).is_error)
        self.host.page_wait = 0.2
        self.assertIn("none is open", self.host.call("notes", self.i, "picked", {},
                                                     Caller(channel="c1")).content[0]["text"])
        self.assertIn("you may not use", self.host.call("notes", self.i, "add", {"text": "x"},
                                                     Caller(channel="c2")).content[0]["text"])
        user = self.host.call("notes", self.i, "add", {"text": "mine"}, Caller(gatherer="g"))   # the user's: no channel
        self.assertFalse(user.is_error)


class PanelToolTest(HostBase):
    def test_a_tool_its_panel_answers_goes_to_an_open_panel_and_waits_for_its_answer(self):
        i = self.host.open("notes", "g", self.folder)
        self.host.attach("g", i.id, "c1")
        sub, leave = self.host.subscribe("notes", i, ["notes.added"])                   # its panel, open
        self.addCleanup(leave)
        got = []
        t = threading.Thread(target=lambda: got.append(self.host.call("notes", i, "picked", {"why": "x"},
                                                                     Caller(channel="c1"))))
        t.start()
        while True:
            name, value = sub.queue.get(timeout=5)
            if name == "message" and value.get("ag") == "call":
                break
        self.assertEqual((value["tool"], value["args"], value["caller"]["channel"]), ("picked", {"why": "x"}, "c1"))
        with self.assertRaises(AppError):
            self.host.answer_panel(i, "not-a-call", {"content": []})
        self.host.answer_panel(i, value["id"], {"content": [{"type": "text", "text": "the second row"}]})
        t.join(5)
        self.assertEqual(got[0].content, [{"type": "text", "text": "the second row"}])
        self.host.tool_wait = 0.2
        self.assertIn("did not answer", self.host.call("notes", i, "picked", {}, Caller(channel="c1")).content[0]["text"])


class LiveTest(HostBase):
    def test_a_panel_follows_its_instance_s_events_and_its_backend_s_messages(self):
        i = self.host.open("notes", "g", self.folder)
        sub, leave = self.host.subscribe("notes", i, ["notes.added", "app_attached"])
        self.addCleanup(leave)
        self.host.attach("g", i.id, "c1")
        self.assertEqual(sub.queue.get(timeout=5), ("message", {"ag": "instance", "attached": ["c1"], "name": ""}))
        self.assertEqual(sub.queue.get(timeout=5), ("message", {"hello": "c1"}))     # its backend's word
        self.host.call("notes", i, "add", {"text": "a"}, Caller(channel="c1"))
        self.host.flush()                                                          # the hub's ring, as ag's notice
        seen = []
        end = time.time() + 10
        while time.time() < end and "notes.added" not in seen:
            try:
                name, value = sub.queue.get(timeout=1)
            except queue.Empty:
                continue
            if name == "event":
                seen.append(value["type"])
        self.assertEqual(seen, ["app_attached", "notes.added"])
        with self.assertRaises(AppError):
            self.host.subscribe("notes", i, ["tool_call"])

    def test_a_panel_s_backend_messages_reach_one_stream_of_it(self):
        """A panel follows its events in a stream per subscription, and its backend's messages (a tool call among them)
        in one stream only: a tool call reaches it once."""
        i = self.host.open("notes", "g", self.folder)
        events, leave = self.host.subscribe("notes", i, ["notes.added"], messages=False)
        self.addCleanup(leave)
        told, leave2 = self.host.subscribe("notes", i, [], messages=True)
        self.addCleanup(leave2)
        self.host.tell(i, {"said": "hi"})
        self.assertEqual(told.queue.get(timeout=5), ("message", {"said": "hi"}))
        self.assertTrue(events.queue.empty())


class GatewayBase(HostBase):
    def setUp(self):
        super().setUp()
        saved = tool_gateway.HOST, tool_gateway.ORIGIN
        tool_gateway.HOST, tool_gateway.ORIGIN = self.host, "http://127.0.0.1:4999"
        self.addCleanup(lambda: setattr(tool_gateway, "HOST", saved[0]) or setattr(tool_gateway, "ORIGIN", saved[1]))
        kept = access.HOST, access.LEAD, access.ROWS
        access.HOST, access.LEAD, access.ROWS = self.host, tool_gateway.lead, lambda: self.rows
        access.STARTED = lambda g, c: c != "fresh"                     # every agent but "fresh" has had a call
        self.host.may_use, self.host.changed = access.may_use, access.settle
        access.forget()
        self.addCleanup(lambda: (setattr(access, "HOST", kept[0]), setattr(access, "LEAD", kept[1]),
                                 setattr(access, "ROWS", kept[2]), setattr(access, "STARTED", None), access.forget()))
        self.rows = [{"session_id": "c1", "gatherer": "g", "cwd": self.folder, "harness": "claude"},
                     {"session_id": "c2", "started_as": "tmp-2", "gatherer": "g", "cwd": self.folder,
                      "harness": "codex"},
                     {"session_id": "c3", "gatherer": "g", "cwd": self.folder, "harness": "antigravity"}]

    def gatherer_toml(self, text):
        with open(os.path.join(self.tmp.name, "ag", "gatherers", "g", "gatherer.toml"), "w") as fh:
            fh.write('policy = "proactive_context_manager"\n' + text)


class GatewayTest(GatewayBase):
    def test_an_agent_sees_its_gatherer_s_apps_tools_named_by_app(self):
        tools = {t["name"]: t for t in tool_gateway.tools("g")}
        self.assertEqual(set(tools), {*tool_gateway.AG_TOOL_NAMES, "notes_add", "notes_picked"})
        self.assertEqual(tools["notes_add"]["description"], "Notes: Add a note.")
        self.assertIn("instance", tools["notes_add"]["inputSchema"]["properties"])
        said = tool_gateway.instructions("g")
        self.assertIn("## Notes (notes)\nKeep notes with notes_add.", said)
        self.assertIn("- Notes (notes): Notes -- used by every agent of the group", said)   # every app installed
        self.assertNotIn("ag apps", said)
        self.assertIn("ag apps call", tool_gateway.instructions("g", cli=True))

    def test_every_app_installed_is_on_in_every_group_whatever_its_gatherer_toml_says(self):
        self.gatherer_toml("apps = []\n")                               # the old key: no longer read
        self.assertEqual([m.name for m in tool_gateway.on("g")], ["notes"])
        self.assertEqual([m.name for m in tool_gateway.on("another")], ["notes"])
        self.assertTrue(tool_gateway.launch_args(self.rows[0]))

    def test_each_harness_is_given_the_apps_as_it_takes_them(self):
        claude = tool_gateway.launch_args(self.rows[0])
        self.assertEqual(claude[0], "--mcp-config")
        self.assertEqual(json.loads(claude[1])["mcpServers"]["ag-apps"]["url"], "http://127.0.0.1:4999/mcp/c1")
        codex = tool_gateway.launch_args(self.rows[1])
        self.assertEqual(codex, ["-c", 'mcp_servers.ag-apps.url="http://127.0.0.1:4999/mcp/tmp-2"'])  # as it started
        agy = " ".join(tool_gateway.launch_args(self.rows[2]))
        self.assertIn("ag apps call", agy)                                             # no MCP: its shell
        self.assertIn("Keep notes with notes_add.", agy)
        self.assertTrue(tool_gateway.served(self.rows[0]))
        self.assertFalse(tool_gateway.served(self.rows[2]))

    def test_a_group_s_app_is_opened_for_the_agent_s_folder_and_used_by_every_agent_attached_to_none(self):
        got = tool_gateway.call(self.rows, "c1", "notes_add", {"text": "milk"})
        self.assertEqual(got, {"content": [{"type": "text", "text": "kept"}], "isError": False})
        (book,) = self.host.instances_of("g", "notes")
        self.assertEqual(book.folder, os.path.realpath(self.folder))
        tool_gateway.call(self.rows, "tmp-2", "notes_add", {"text": "eggs"})        # codex, by the id it started as
        self.assertEqual(self.host.instances_of("g", "notes"), [book])              # the folder's one, shared
        self.assertEqual((self.host.agents_of(book), tasks.of("g")["tasked"]), ([], {}))   # no one attached, no task
        self.host.flush()
        self.assertEqual([(e["properties"]["channel"], e["payload"]["text"]) for e in
                          self.host.read("notes", book, ["notes.added"])], [("c1", "milk"), ("c2", "eggs")])

    def test_a_task_s_app_is_used_by_the_agents_in_its_task_alone_checked_at_each_call(self):
        write_app(self.apps_dir, "book", book_toml("many", "task"), BOOK)
        self.host.find()
        self.assertNotIn("book_add", {t["name"] for t in tool_gateway.tools("g", ("c1",))})   # none of its: not given
        got = tool_gateway.call(self.rows, "c1", "book_add", {"text": "x"})
        self.assertTrue(got["isError"])
        self.assertIn("Book: you may use none of its instances", got["content"][0]["text"])
        self.assertIn("None is open in your group", got["content"][0]["text"])
        book = self.host.open("book", "g", self.folder)
        task_links.change("g", lambda: tasks.add("g", "c1", ["app:" + book.id]))   # c1 and the Book: one task
        self.assertIn("book_add", {t["name"] for t in tool_gateway.tools("g", ("c1",))})
        self.assertFalse(tool_gateway.call(self.rows, "c1", "book_add", {"text": "x"})["isError"])
        got = tool_gateway.call(self.rows, "tmp-2", "book_add", {"text": "y", "instance": book.id})
        self.assertIn("you may not use Book", got["content"][0]["text"])                     # c2: not in its task
        got = tool_gateway.call(self.rows, "tmp-2", "book_add", {"text": "y"})
        self.assertIn(f"{access.shown(book)} in task:1", got["content"][0]["text"])        # which task holds one
        task_links.change("g", lambda: tasks.take_out("g", ["c1"]))                          # c1 leaves: refused at once
        self.assertTrue(tool_gateway.call(self.rows, "c1", "book_add", {"text": "z"})["isError"])
        refused = self.host.call("book", book, "add", {"text": "z"}, Caller(channel="c1", gatherer="g"))
        self.assertTrue(refused.is_error)                                                    # the host asks again

    def test_apps_call_reaches_an_app_not_given_by_name_with_the_same_check(self):
        write_app(self.apps_dir, "book", book_toml("many", "task"), BOOK)
        self.host.find()
        book = self.host.open("book", "g", self.folder)
        task_links.change("g", lambda: tasks.add("g", "c1", ["app:" + book.id]))
        got = tool_gateway.call(self.rows, "c1", "apps_call", {"app": "book", "tool": "add", "arguments": {"text": "a"}})
        self.assertEqual(got["content"][0]["text"], "kept")
        got = tool_gateway.call(self.rows, "c1", "apps_call", {"app": "book", "tool": "add", "text": "b"})
        self.assertEqual(got["content"][0]["text"], "kept")                     # its arguments beside `arguments`
        got = tool_gateway.call(self.rows, "c2", "apps_call", {"app": "book", "tool": "book_add",
                                                               "arguments": {"text": "a"}, "instance": book.id})
        self.assertTrue(got["isError"])

    def test_the_tools_for_the_apps_themselves_say_what_is_installed_and_what_an_agent_may_use(self):
        write_app(self.apps_dir, "book", book_toml("many", "task"), BOOK)
        self.host.find()
        book = self.host.open("book", "g", self.folder)
        self.host.rename("g", book.id, "Trip")
        task_links.change("g", lambda: tasks.add("g", "c1", ["c2", "app:" + book.id], "Plan"))
        listed = tool_gateway.call(self.rows, "c3", "apps_list", {})["content"][0]["text"]
        self.assertIn("- Book (book): Book. Used by the agents in its task. Tools: book_add, book_picked.", listed)
        self.assertIn("- Notes (notes): Notes. Used by every agent of the group.", listed)
        helped = tool_gateway.call(self.rows, "c3", "apps_help", {"app": "book"})["content"][0]["text"]
        self.assertIn("Keep notes with notes_add.", helped)
        self.assertIn('"name": "book_add"', helped)
        mine = tool_gateway.call(self.rows, "c1", "apps_mine", {})["content"][0]["text"]
        self.assertIn(f"- Book 'Trip' (id {book.id}) in {book.folder}: your task 'Plan' "
                      f"(with actors c2)", mine)
        self.assertIn("None is open for you now", tool_gateway.call(self.rows, "c3", "apps_mine", {})
                      ["content"][0]["text"])
        self.assertTrue(tool_gateway.call(self.rows, "c3", "apps_help", {"app": "nope"})["isError"])

    def test_an_agent_is_told_when_its_task_gains_or_loses_an_app_s_instance(self):
        write_app(self.apps_dir, "book", book_toml("many", "task"), BOOK)
        self.host.find()
        told = []
        self.host.tell_agent = lambda g, c, text, record: told.append((c, text, record["can"]))
        task_links.change("g", lambda: tasks.add("g", "c1", ["c2"], "Plan"))
        book = self.host.open("book", "g", self.folder)
        task_links.change("g", lambda: tasks.add("g", "c1", ["app:" + book.id, "fresh"]))
        self.assertEqual(sorted((c, can) for c, _, can in told), [("c1", True), ("c2", True)])   # not "fresh":
                                                                                                 # given it at start
        self.assertIn(f"You can now use {access.shown(book)}: it is in your task 'Plan'.", told[0][1])
        told.clear()
        self.host.rename("g", book.id, "Trip")
        self.assertIn("is now called: Book 'Trip'", told[0][1])
        told.clear()
        task_links.change("g", lambda: tasks.take_out("g", ["c2"]))
        self.assertEqual([(c, can) for c, _, can in told], [("c2", False)])
        told.clear()
        self.host.close_instance("g", book.id)
        task_links.closed("g", book.id)
        self.assertEqual([(c, can) for c, _, can in told], [("c1", False)])

    def test_an_app_every_agent_of_the_group_may_use_is_put_in_no_task(self):
        notes = self.host.open("notes", "g", self.folder)                          # access "group"
        item = "app:" + notes.id
        self.assertEqual((task_links.taskable("g", item), task_links.taskable("g", "c1")), (False, True))
        self.assertFalse(task_links.link("g", notes.id, "c1", move=True))          # not even by the reader's attaching
        self.assertEqual((tasks.of("g")["tasked"], self.host.agents_of(notes)), ({}, []))
        write_app(self.apps_dir, "book", book_toml("many", "task"), BOOK)
        self.host.find()
        book = self.host.open("book", "g", self.folder)
        self.assertTrue(task_links.taskable("g", "app:" + book.id))                 # a task's app: as before
        tasks.add("g", "c1", [item, "c2"])                                          # put in one before the rule
        task_links.on_load("g")                                                     # its group read: out of it
        self.assertNotIn(item, tasks.of("g")["tasked"])
        self.assertEqual(set(tasks.of("g")["tasked"]), {"c1", "c2"})
        self.assertFalse(tool_gateway.call(self.rows, "c3", "notes_add", {"text": "x"})["isError"])   # still everyone's

    def test_an_app_s_message_names_the_instance_it_is_from(self):
        i = self.host.open("notes", "g", self.folder)
        self.host.rename("g", i.id, "Trip")
        self.assertEqual(app_host.stream_of("Notes", i), f"Notes ({i.id})")
        self.assertEqual(app_host.stream_of("Notes", self.host.instance("g", i.id)), f"Notes · Trip ({i.id})")

    def test_the_gatherer_agent_reaches_every_app_attached_to_none(self):
        write_app(self.apps_dir, "book", book_toml("per-folder", "task"), BOOK)
        self.host.find()
        lead = {"session_id": "lead", "gatherer": "g", "cwd": self.folder, "harness": "claude", "role": "coordinator"}
        rows = self.rows + [lead]
        self.rows.append(lead)
        sessions = unittest.mock.patch.object(task_links, "SESSIONS", unittest.mock.Mock(list=lambda: rows))
        sessions.start()
        self.addCleanup(sessions.stop)
        self.host.attachable = task_links.attachable
        self.assertNotIn("book_add", {t["name"] for t in tool_gateway.tools("g")})  # a task's app: not given others
        self.assertIn("book_add", {t["name"] for t in tool_gateway.tools("g", head=True)})   # every app, for it
        self.assertIn(tool_gateway.LEAD, tool_gateway.instructions("g", head=True))
        self.assertIn("## Book (book)", tool_gateway.instructions("g", head=True))
        got = tool_gateway.call(rows, "lead", "book_add", {"text": "milk"})       # none open: one opened for it
        self.assertEqual(got, {"content": [{"type": "text", "text": "kept"}], "isError": False})
        (book,) = self.host.instances_of("g", "book")
        self.assertEqual((self.host.agents_of(book), self.host.attached_to("g", "lead")), ([], []))
        self.assertFalse(tool_gateway.call(rows, "lead", "book_add", {"text": "eggs"})["isError"])   # the one open
        self.assertEqual(len(self.host.instances_of("g", "book")), 1)
        other = self.host.open("book", "g", tempfile.mkdtemp(dir=self.tmp.name))
        got = tool_gateway.call(rows, "lead", "book_add", {"text": "x"})            # two open: say which
        self.assertIn("2 of Book you may use: say which with `instance`", got["content"][0]["text"])
        self.assertFalse(tool_gateway.call(rows, "lead", "book_add", {"text": "x", "instance": other.id})["isError"])
        self.assertEqual(self.host.attached_to("g", "lead"), [])
        self.assertEqual(tasks.of("g")["tasked"], {})                               # in no task, nor its apps
        with self.assertRaises(AppError):                                           # nor attached by anyone
            self.host.attach("g", book.id, "lead")
        self.assertEqual(sorted(i["id"] for i in next(a for a in tool_gateway.listed(rows, "lead")["apps"]
                                                       if a["name"] == "book")["usable"]), sorted([book.id, other.id]))

    def test_an_agent_that_may_use_several_says_which(self):
        write_app(self.apps_dir, "book", book_toml("many", "task"), BOOK)
        self.host.find()
        a, b = self.host.open("book", "g", self.folder), self.host.open("book", "g", self.folder)
        task_links.change("g", lambda: tasks.add("g", "c1", ["app:" + a.id, "app:" + b.id]))
        self.host.rename("g", b.id, "Trip")                          # named by the user: said by that name
        got = tool_gateway.call(self.rows, "c1", "book_add", {"text": "x"})
        self.assertTrue(got["isError"])
        self.assertIn("say which with `instance`", got["content"][0]["text"])
        self.assertIn(f"Book 'Trip' (id {b.id})", got["content"][0]["text"])
        self.assertFalse(tool_gateway.call(self.rows, "c1", "book_add", {"text": "x", "instance": b.id})["isError"])
        self.assertIn("you may not use Book 'Trip'",
                      tool_gateway.call(self.rows, "c2", "book_add", {"text": "x", "instance": b.id})
                      ["content"][0]["text"])

    def test_what_is_refused_is_said_to_the_agent(self):
        self.assertIn("no such tool", tool_gateway.call(self.rows, "c1", "notes_nope", {})["content"][0]["text"])
        self.assertIn("not an actor this dashboard runs",
                      tool_gateway.call(self.rows, "zzz", "notes_add", {})["content"][0]["text"])


class GatewayServedTest(GatewayBase):
    """The apps' MCP server at /mcp/<actor>, and `ag apps` reaching the same through the dashboard."""

    def setUp(self):
        super().setUp()
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        self.httpd.app_host._write_fn = insert_here
        self.hosts.append(self.httpd.app_host)
        rows = self.rows
        self.httpd.sessions.list = lambda: [dict(r) for r in rows]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.serving(self.httpd)                          # stopped before the home goes
        self.port = self.httpd.server_port

    def rpc(self, actor, method, params=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", f"/mcp/{actor}", json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                          "params": params or {}}),
                     {"Content-Type": "application/json"})
        r = conn.getresponse()
        got = json.loads(r.read())
        conn.close()
        return got

    def test_a_closed_server_s_host_is_no_longer_the_gateway_s(self):
        self.assertIs(tool_gateway.HOST, self.httpd.app_host)
        self.assertTrue(tool_gateway.served(self.rows[0]))
        self.httpd.shutdown()
        self.httpd.server_close()
        self.assertIsNone(tool_gateway.HOST)
        self.assertFalse(tool_gateway.served(self.rows[0]))     # a session started after it: given no tools of a closed host

    def test_the_mcp_server_lists_instructs_and_calls(self):
        init = self.rpc("c1", "initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(init["serverInfo"]["name"], "ag-apps")
        self.assertIn("Keep notes with notes_add.", init["instructions"])
        names = [t["name"] for t in self.rpc("c1", "tools/list")["result"]["tools"]]
        self.assertEqual(names, [*tool_gateway.AG_TOOL_NAMES, "notes_add", "notes_picked"])
        got = self.rpc("c1", "tools/call", {"name": "notes_add", "arguments": {"text": "milk"}})["result"]
        self.assertEqual(got["content"][0]["text"], "kept")
        self.assertIsNotNone(__import__("ag_dashboard.mcp", fromlist=["listed"]).listed(tool_gateway.endpoint("c1")))
        self.assertIn("not an actor", json.dumps(self.rpc("zzz", "tools/list")))

    def post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
        r = conn.getresponse()
        got = (r.status, json.loads(r.read() or b"{}"))
        conn.close()
        return got

    def test_the_routes_refuse_a_group_s_app_in_a_task(self):
        notes = self.httpd.app_host.open("notes", "g", self.folder)
        status, got = self.post("/api/tasks", {"gatherer": "g", "do": "add", "to": "c1", "items": ["app:" + notes.id]})
        self.assertGreaterEqual(status, 400)
        self.assertIn("isn't put in a task", got.get("error", ""))
        status, got = self.post("/api/apps/attach", {"gatherer": "g", "instance": notes.id, "channel": "c1"})
        self.assertEqual(status, 409)
        self.assertIn("every agent of the group can use Notes", got.get("error", ""))
        status, _ = self.post("/api/apps/open", {"app": "notes", "gatherer": "g", "folder": self.folder, "channel": "c1"})
        self.assertEqual(status, 200)                                                # opened, in no task
        self.assertEqual(tasks.of("g")["tasked"], {})

    def test_ag_apps_lists_and_calls_as_the_actor_it_runs_in(self):
        env = {"AG_DASHBOARD": f"http://127.0.0.1:{self.port}", "AG_ACTOR": "c3"}
        for v in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
            env[v] = ""
        with unittest.mock.patch.dict(os.environ, env):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(apps_cli.main(["call", "notes_add", '{"text": "from the shell"}']), 0)
            self.assertEqual(out.getvalue().strip(), "kept")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(apps_cli.main([]), 0)
            listed = out.getvalue()
            self.assertIn("Notes (notes) -- you may use:", listed)
            self.assertIn("notes_add(text): Add a note.", listed)
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(apps_cli.main(["call", "notes_add", "not json"]), 1)
            self.assertIn("not JSON", err.getvalue())


REMOTE = NOTES.replace('name = "notes"', 'name = "far_notes"').replace(
    'python = "backend:NotesApp"', f'command = ["{sys.executable}", "-m", "app_kit.remote", "backend:NotesApp"]'
).replace('name = "notes.added"', 'name = "far_notes.added"')


class ServedTest(HostBase):
    """The routes, an app in its own process reaching the host, and each app's own origin."""

    def setUp(self):
        super().setUp()
        write_app(self.apps_dir, "far_notes", REMOTE, BACKEND.replace("notes.added", "far_notes.added"))
        env = unittest.mock.patch.dict(os.environ, {"PYTHONPATH": ROOT})
        env.start()
        self.addCleanup(env.stop)
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        self.httpd.app_host._write_fn = insert_here
        self.hosts.append(self.httpd.app_host)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.serving(self.httpd)                          # stopped before the home goes
        self.port = self.httpd.server_port

    def ask(self, method, path, body=None, host=None, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if origin:
            headers["Origin"] = origin
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), raw

    def api(self, method, path, body=None):
        status, _, raw = self.ask(method, path, body)
        return status, json.loads(raw)

    def test_the_page_opens_attaches_and_reads(self):
        status, got = self.api("GET", "/api/apps?gatherer=g")
        self.assertEqual(status, 200)
        self.assertEqual({a["name"] for a in got["apps"]}, {"notes", "far_notes"})
        status, inst = self.api("POST", "/api/apps/open", {"app": "notes", "gatherer": "g", "folder": self.folder,
                                                           "channel": "c1"})
        self.assertEqual(status, 200)
        status, got = self.api("POST", "/api/apps/call", {"app": "notes", "gatherer": "g", "instance": inst["id"],
                                                          "tool": "add", "args": {"text": "x"}})
        self.assertEqual((status, got["isError"]), (200, False))
        self.httpd.app_host.flush()
        status, got = self.api("GET", f"/api/apps/events?app=notes&gatherer=g&instance={inst['id']}&types=notes.added")
        self.assertEqual([e["payload"] for e in got["events"]], [{"text": "x"}])
        status, got = self.api("POST", "/api/apps/insert", {"app": "notes", "gatherer": "g", "instance": inst["id"],
                                                            "events": [{"type": "user_message", "payload": {}}]})
        self.assertEqual(status, 403)
        self.assertEqual(self.api("GET", "/api/apps/events?app=notes&gatherer=g&instance=nope&types=x")[0], 404)
        status, got = self.api("POST", "/api/apps/rename", {"gatherer": "g", "instance": inst["id"], "name": " Trip "})
        self.assertEqual((status, got["name"]), (200, "Trip"))
        self.assertEqual(self.api("GET", "/api/apps?gatherer=g")[1]["instances"][0]["name"], "Trip")
        self.assertEqual(self.api("POST", "/api/apps/rename", {"gatherer": "g", "instance": "nope", "name": "x"})[0], 404)
        self.assertEqual(self.api("POST", "/api/apps/rename", {"gatherer": "g", "instance": inst["id"], "name": 3})[0], 400)

    def test_an_app_and_the_agents_working_with_it_are_one_task(self):
        """task_links.py through the routes: an app opened by an agent put in a task with it; another the reader attaches
        put in it too, and detached taken out; the app closed, out of it. (An app of the agents in its task: a group's
        is in no task.)"""
        write_app(self.apps_dir, "book", book_toml("per-folder", "task"), BOOK)
        self.httpd.app_host.find()
        _, inst = self.api("POST", "/api/apps/open", {"app": "book", "gatherer": "g", "folder": self.folder,
                                                      "channel": "c1"})
        item, host = "app:" + inst["id"], self.httpd.app_host
        tasked = lambda: self.api("GET", "/api/apps?gatherer=g")[1]["tasks"]["tasked"]   # noqa: E731
        agents = lambda: host.agents_of(host.instance("g", inst["id"]))                    # noqa: E731
        self.assertEqual(set(tasked()), {"c1", item})
        self.assertEqual(self.api("POST", "/api/apps/attach", {"gatherer": "g", "instance": inst["id"],
                                                               "channel": "c2"})[0], 200)
        self.assertEqual((set(tasked()), agents()), ({"c1", "c2", item}, ["c1", "c2"]))
        self.assertEqual(self.api("POST", "/api/apps/detach", {"gatherer": "g", "instance": inst["id"],
                                                               "channel": "c2"})[0], 200)
        self.assertEqual((set(tasked()), agents()), ({"c1", item}, ["c1"]))
        self.assertEqual(self.api("POST", "/api/apps/close", {"gatherer": "g", "instance": inst["id"]})[0], 200)
        self.assertEqual(tasked(), {})
        self.assertEqual(self.api("POST", "/api/apps/attach", {"gatherer": "g", "instance": "nope", "channel": "c2"})[0],
                         404)

    def test_an_app_in_its_own_process_reaches_the_host_with_its_token(self):
        status, inst = self.api("POST", "/api/apps/open", {"app": "far_notes", "gatherer": "g",
                                                           "folder": self.folder, "channel": "c1"})
        self.assertEqual(status, 200, inst)
        self.assertEqual(inst["title"], "Notes")                           # its own process opened it
        status, got = self.api("POST", "/api/apps/call", {"app": "far_notes", "gatherer": "g", "instance": inst["id"],
                                                          "tool": "add", "args": {"text": "far"}})
        self.assertEqual((status, got["isError"]), (200, False), got)
        self.httpd.app_host.flush()
        events = self.httpd.app_host.read("far_notes", self.httpd.app_host.instance("g", inst["id"]),
                                          ["far_notes.added"])
        self.assertEqual([e["payload"] for e in events], [{"text": "far"}])
        status, _, raw = self.ask("POST", "/apps/host/far_notes/attached", {"instance": inst})
        self.assertEqual(status, 401)                                      # no token: not the app

    def test_an_app_s_origin_serves_its_panel_and_backend_and_nothing_of_the_dashboard(self):
        host = f"notes.localhost:{self.port}"
        status, headers, raw = self.ask("GET", "/", host=host)
        self.assertEqual((status, raw), (200, b"<!doctype html><title>Notes</title>"))
        self.assertIn(f"frame-ancestors 'self' http://127.0.0.1:{self.port}", headers["content-security-policy"])
        self.assertEqual(self.ask("GET", "/api/home", host=host)[0], 404)          # the dashboard's: not here
        self.assertEqual(self.ask("GET", "/api/apps", host=host)[0], 404)
        self.assertEqual(self.ask("GET", "/../app.toml", host=host)[0], 404)
        self.assertEqual(self.ask("GET", "/%2e%2e/backend.py", host=host)[0], 404)
        self.assertEqual(self.ask("GET", "/", host=f"nosuch.localhost:{self.port}")[0], 404)
        _, inst = self.api("POST", "/api/apps/open", {"app": "notes", "gatherer": "g", "folder": self.folder})
        status, _, raw = self.ask("GET", f"/api/count?gatherer=g&instance={inst['id']}", host=host)
        self.assertEqual((status, json.loads(raw)), (200, {"n": 0, "method": "GET"}))
        q = f"/api/count?gatherer=g&instance={inst['id']}"
        self.assertEqual(self.ask("POST", q, {}, host=host)[0], 403)                 # a write from no origin
        self.assertEqual(self.ask("POST", q, {}, host=host, origin=f"http://other.localhost:{self.port}")[0], 403)
        self.assertEqual(self.ask("POST", q, {}, host=host, origin=f"http://notes.localhost:{self.port}")[0], 200)
        status, headers, raw = self.ask("GET", "/_ag/app.js", host=host)                 # the panels' SDK, on its origin
        self.assertEqual(status, 200)
        self.assertIn("AgApp", raw.decode())
        self.assertIn("javascript", headers["content-type"])
        status, _, raw = self.ask("POST", "/api/apps/open", {"app": "notes", "gatherer": "g"}, host=host)
        self.assertEqual((status, raw), (403, b"only the app's own panel may do that"))     # the app's /api, not ours


if __name__ == "__main__":
    unittest.main()
