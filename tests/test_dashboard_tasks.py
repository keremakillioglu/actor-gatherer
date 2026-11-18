"""tasks.py: actors and apps kept together as one task -- made by putting one in another's, taken out, renamed, gone
once one item is left, and those sharing an app grouped once -- and task_links.py: every agent of a task attached to
every app of it, joining and leaving."""

import os
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import access, home as dashboard_home  # noqa: E402
from ag_dashboard import task_links, tasks, tool_gateway  # noqa: E402


class TasksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.was = dashboard_home.HOME
        dashboard_home.HOME = os.path.join(self.tmp.name, "ag")

    def tearDown(self):
        dashboard_home.HOME = self.was
        self.tmp.cleanup()

    def test_nothing_kept_is_nothing(self):
        self.assertEqual((tasks.stored(), tasks.of("g")), ({}, {"tasks": [], "tasked": {}}))

    def test_an_actor_put_in_a_lone_actor_s_task_makes_one_of_the_two(self):
        tid = tasks.add("g", "a", ["b"], "  Book   the trip ")
        self.assertEqual(tasks.of("g"), {"tasks": [{"id": tid, "name": "Book the trip"}], "tasked": {"a": tid, "b": tid}})
        self.assertEqual(tasks.members("g", tid), ["a", "b"])
        self.assertEqual(tasks.add("g", "b", ["c"], "ignored: it has one"), tid)       # put in the task `b` is in
        self.assertEqual(tasks.members("g", tid), ["a", "b", "c"])
        self.assertEqual(tasks.of("h"), {"tasks": [], "tasked": {}})                    # another gatherer's: none

    def test_one_left_and_the_task_is_gone(self):
        tid = tasks.add("g", "a", ["b", "c"], "Trip")
        tasks.take_out("g", ["c"])
        self.assertEqual(tasks.members("g", tid), ["a", "b"])
        tasks.take_out("g", ["a"])                                                       # `b` left alone: no task
        self.assertEqual(tasks.of("g"), {"tasks": [], "tasked": {}})

    def test_an_actor_moved_to_another_task_leaves_its_old_one(self):
        trip = tasks.add("g", "a", ["b"], "Trip")
        fix = tasks.add("g", "x", ["y"], "Fix")
        tasks.add("g", "x", ["b"])                                                       # `b` to Fix: Trip has `a` only
        self.assertEqual(tasks.of("g"), {"tasks": [{"id": fix, "name": "Fix"}], "tasked": {"x": fix, "y": fix, "b": fix}})
        self.assertNotEqual(trip, fix)

    def test_what_is_refused(self):
        with self.assertRaisesRegex(tasks.TaskError, "which actors or apps"):
            tasks.add("g", "a", ["a"], "Trip")                                           # itself: no one to add
        with self.assertRaisesRegex(tasks.TaskError, "which gatherer"):
            tasks.add("", "a", ["b"], "Trip")
        tid = tasks.add("g", "a", ["b"], "Trip")
        tasks.rename("g", tid, " Book  it ")
        self.assertEqual(tasks.of("g")["tasks"], [{"id": tid, "name": "Book it"}])
        with self.assertRaisesRegex(tasks.TaskError, "no task 99 in g"):
            tasks.rename("g", 99, "x")
        tasks.rename("g", tid, "   ")                                  # no name: named by what is in it again
        self.assertEqual(tasks.of("g")["tasks"], [{"id": tid, "name": ""}])

    def test_apps_are_items_and_a_task_made_unnamed_is_named_by_what_is_in_it(self):
        tid = tasks.add("g", tasks.app_item("b1"), ["a"])
        self.assertEqual(tasks.of("g"), {"tasks": [{"id": tid, "name": ""}], "tasked": {"app:b1": tid, "a": tid}})
        self.assertEqual((tasks.app_of("app:b1"), tasks.app_of("a")), ("b1", None))
        tasks.take_out("g", ["app:b1"])                                                  # `a` left alone: no task
        self.assertEqual(tasks.of("g"), {"tasks": [], "tasked": {}})

    def test_items_sharing_an_app_are_made_one_task_once(self):
        trip = tasks.add("g", "a", ["b"], "Trip")
        got = tasks.group("g", [["app:b1", "b", "c"], ["app:n1"], ["app:x", "y"]])
        self.assertEqual(len(got), 2)
        have = tasks.of("g")["tasked"]
        self.assertEqual({x for x, t in have.items() if t == trip}, {"a", "b", "c", "app:b1"})   # into the task it had
        new = have["y"]
        self.assertNotEqual(new, trip)
        self.assertEqual((have["app:x"], "app:n1" in have), (new, False))                    # alone: in none
        self.assertEqual(next(t["name"] for t in tasks.of("g")["tasks"] if t["id"] == new), "")
        self.assertEqual(tasks.group("g", [["app:n1", "z"]]), [])                            # once
        self.assertTrue(tasks.grouped("g"))
        self.assertFalse(tasks.grouped("h"))

    def test_two_tasks_sharing_an_app_become_one(self):
        trip = tasks.add("g", "a", ["b"], "Trip")
        fix = tasks.add("g", "x", ["y"], "Fix")
        tasks.group("g", [["app:b1", "b", "x"]])
        self.assertEqual(tasks.of("g"), {"tasks": [{"id": trip, "name": "Trip"}],
                                         "tasked": {**{c: trip for c in ("a", "b", "x", "y", "app:b1")}}})
        self.assertNotIn(fix, [t["id"] for t in tasks.of("g")["tasks"]])


class Host:
    """An app host as task_links.py uses it: attachments, kept as {instance: {channel}}."""

    def __init__(self, instances=()):
        import threading

        class Instance:
            def __init__(self, iid):
                self.id, self.gatherer, self.app, self.name, self.title, self.folder = iid, "g", iid[:1], "", "", None
        self.lock = threading.RLock()
        self.apps = {}
        self.instances = {i: Instance(i) for i in instances}
        self.attached = {i: set() for i in instances}
        self.log = []

    def attach(self, gatherer, iid, channel, by="user"):
        if iid not in self.instances:
            raise tool_gateway.AppError(f"{iid}: no such instance")
        self.attached[iid].add(channel)
        self.log.append(("attach", iid, channel))

    def detach(self, gatherer, iid, channel, by="user"):
        if channel in self.attached.get(iid, set()):
            self.attached[iid].discard(channel)
            self.log.append(("detach", iid, channel))

    def instances_of(self, gatherer, app=None):
        return [i for i in self.instances.values() if i.gatherer == gatherer]

    def tell_agent(self, gatherer, channel, text, record):
        self.log.append(("told", channel, text))


class TaskLinksTest(TasksTest):
    def setUp(self):
        super().setUp()
        self.host = Host(["b1", "n1"])
        patch = unittest.mock.patch.object(tool_gateway, "HOST", self.host)
        patch.start()
        self.addCleanup(patch.stop)
        started = unittest.mock.patch.object(access, "STARTED", lambda g, c: True)   # every agent has had a call
        started.start()
        self.addCleanup(started.stop)

    def test_joining_a_task_attaches_every_agent_to_every_app_and_leaving_detaches(self):
        task_links.change("g", lambda: tasks.add("g", "a", ["app:b1"]))
        self.assertEqual(self.host.attached, {"b1": {"a"}, "n1": set()})
        tid, got = task_links.change("g", lambda: tasks.add("g", "a", ["new", "app:n1"]))
        self.assertEqual(got, {"a": ["n1"], "new": ["b1", "n1"]})
        self.assertEqual(self.host.attached, {"b1": {"a", "new"}, "n1": {"a", "new"}})
        task_links.change("g", lambda: tasks.take_out("g", ["new"]))
        self.assertEqual(self.host.attached, {"b1": {"a"}, "n1": {"a"}})
        task_links.change("g", lambda: tasks.take_out("g", ["app:b1"]))                     # `a` and n1 still one task
        self.assertEqual(self.host.attached, {"b1": set(), "n1": {"a"}})
        task_links.change("g", lambda: tasks.take_out("g", ["a"]))                           # n1 alone: the task gone
        self.assertEqual((self.host.attached, tasks.of("g")["tasks"]), ({"b1": set(), "n1": set()}, []))

    def test_an_app_used_joins_the_agents_task_and_one_in_a_task_only_when_moved(self):
        trip = tasks.add("g", "a", ["b"], "Trip")
        task_links.link("g", "b1", "a")                                                      # b1 in none: into Trip
        self.assertEqual(tasks.task_of("g", "app:b1"), trip)
        self.assertEqual(self.host.attached["b1"], {"a", "b"})                               # every agent of Trip
        task_links.link("g", "n1", "x")                                                      # both alone: a new task
        fix = tasks.task_of("g", "x")
        self.assertEqual((tasks.task_of("g", "app:n1"), self.host.attached["n1"]), (fix, {"x"}))
        task_links.link("g", "b1", "x")                                                      # both in tasks: as they are
        self.assertEqual(tasks.task_of("g", "x"), fix)
        task_links.link("g", "b1", "x", move=True)                                           # the reader's: x moved
        self.assertEqual((tasks.task_of("g", "x"), tasks.task_of("g", "app:n1")), (trip, None))
        self.assertEqual(self.host.attached, {"b1": {"a", "b", "x"}, "n1": set()})        # n1 alone: x detached

    def test_detached_by_the_reader_an_agent_leaves_the_apps_task(self):
        task_links.change("g", lambda: tasks.add("g", "a", ["b", "app:b1", "app:n1"]))
        task_links.unlink("g", "b1", "b")
        self.assertIsNone(tasks.task_of("g", "b"))
        self.assertEqual(self.host.attached, {"b1": {"a"}, "n1": {"a"}})
        self.host.attach("g", "b1", "x")                                                     # not in its task: detached
        task_links.unlink("g", "b1", "x")
        self.assertEqual(self.host.attached["b1"], {"a"})

    def test_a_closed_app_leaves_its_task(self):
        task_links.change("g", lambda: tasks.add("g", "a", ["b", "app:b1"]))
        task_links.closed("g", "b1")
        self.assertEqual(set(tasks.of("g")["tasked"]), {"a", "b"})

    def test_on_load_drops_the_gatherer_agent_s_attachments(self):
        lead = unittest.mock.Mock(list=lambda: [{"session_id": "lead", "role": "coordinator"}])
        with unittest.mock.patch.object(task_links, "SESSIONS", lead):
            self.assertFalse(task_links.attachable("g", "lead"))
            self.assertTrue(task_links.attachable("g", "a"))
            self.host.attached["n1"] = {"a", "lead"}
            task_links.on_load("g")
            self.assertEqual(self.host.attached["n1"], {"a"})
            self.assertIn(("detach", "n1", "lead"), self.host.log)
            self.assertIsNone(tasks.task_of("g", "lead"))

    def test_on_load_groups_what_shares_an_app_once(self):
        self.host.attached["b1"] = {"a", "b"}
        task_links.on_load("g")
        tid = tasks.task_of("g", "a")
        self.assertEqual({x for x, t in tasks.of("g")["tasked"].items() if t == tid}, {"a", "b", "app:b1"})
        self.host.attached["n1"] = {"c"}
        task_links.on_load("g")                                                              # once
        self.assertIsNone(tasks.task_of("g", "c"))
        self.assertEqual(self.host.attached["n1"], set())                                    # not in its task: dropped

    def test_an_agent_is_attached_only_to_the_apps_of_its_task(self):
        trip, fix = tasks.add("g", "a", ["app:b1"], "Trip"), tasks.add("g", "x", ["app:n1"], "Fix")
        self.assertFalse(task_links.link("g", "b1", "x"))                                    # each in a task: nothing
        self.assertNotIn("x", self.host.attached["b1"])
        self.assertEqual((tasks.task_of("g", "x"), tasks.task_of("g", "app:b1")), (fix, trip))
        self.host.attached["b1"].add("x")                                                    # as `link` once made it
        self.assertEqual(task_links.strays("g"), [("b1", "x")])                              # dropped, and told
        self.assertEqual(self.host.attached["b1"], set())
        self.assertIn("x", [e[1] for e in self.host.log if e[0] == "told"])


if __name__ == "__main__":
    unittest.main()
