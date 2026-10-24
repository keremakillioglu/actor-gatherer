"""Each actor's avatar (ag_dashboard/avatars.py): the pictures in the folder, who is given which and
kept, the open actors of a gatherer in different hues, and the server serving them."""
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import avatars, server  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

CIRCLE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"{}><circle cx="32" cy="32" r="32"/></svg>'


def actor(channel, created, status="idle"):
    return {"channel": channel, "created": created, "status": status}


class AvatarsBase(unittest.TestCase):
    """A home of the test's own, and a folder of pictures of its own: `pictures` {name: hue}."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = dashboard_home.HOME, avatars.DIR
        dashboard_home.HOME = os.path.join(self.tmp.name, "ag")
        avatars.DIR = os.path.join(self.tmp.name, "avatars")

    def tearDown(self):
        dashboard_home.HOME, avatars.DIR = self.saved
        self.tmp.cleanup()

    def pictures(self, named):
        for name, hue in named.items():
            os.makedirs(os.path.join(avatars.DIR, name.split("/")[0]), exist_ok=True)
            with open(os.path.join(avatars.DIR, name + ".svg"), "w") as fh:
                fh.write(CIRCLE.format(f' data-hue="{hue}"' if hue else ""))

    def given(self, home):
        return {(g["name"], a["channel"]): a["avatar"] for g in home["gatherers"] for a in g["agents"]}


class AvatarsTest(AvatarsBase):
    def test_the_pool_is_every_picture_in_the_folder_by_its_hue(self):
        self.assertEqual(avatars.pictures(), {})                              # no folder: none
        self.pictures({"robot/a-red": "red", "food/pear": "lime", "animal/odd": None})
        for name in ("robot/notes.txt", "robot/Bad Name.svg"):
            with open(os.path.join(avatars.DIR, name), "w") as fh:
                fh.write("x")
        self.assertEqual(avatars.pictures(), {"animal/odd": "animal/odd", "food/pear": "lime", "robot/a-red": "red"})
        self.assertTrue(avatars.path("food/pear").endswith(os.path.join("food", "pear.svg")))
        for name in ("food/none", "../secret", "food/../food/pear", "pear", ""):
            self.assertIsNone(avatars.path(name), name)

    def test_each_actor_is_given_one_of_its_own_and_keeps_it(self):
        self.pictures({f"robot/r{i}": h for i, h in enumerate(["red", "blue", "green", "pink"])})
        home = {"gatherers": [{"name": "g", "agents": [actor("c1", 1), actor("c2", 2)]},
                              {"name": "h", "agents": [actor("c1", 3)]}]}
        first = self.given(avatars.assign(home))
        self.assertEqual(len(set(first.values())), 3)                         # three actors, three pictures
        self.assertEqual(avatars.stored(), first)
        home["gatherers"][0]["agents"].insert(0, actor("c3", 4))
        again = self.given(avatars.assign(home))
        self.assertEqual({k: v for k, v in again.items() if k in first}, first)   # each keeps its own
        self.assertEqual(len(set(again.values())), 4)                         # the new one: the one left
        self.assertEqual(self.given(avatars.assign(home)), again)             # nothing new: nothing changes

    def test_the_open_actors_of_a_gatherer_are_in_different_hues(self):
        self.pictures({"robot/red-1": "red", "robot/red-2": "red", "animal/blue": "blue", "food/green": "green"})
        home = {"gatherers": [{"name": "g", "agents": [actor("c3", 3), actor("c2", 2), actor("c1", 1)]}]}
        hues = avatars.pictures()
        got = self.given(avatars.assign(home))
        self.assertEqual(len({hues[n] for n in got.values()}), 3)
        # a closed actor's hue is free: the new open actor may take it, never an open one's
        home["gatherers"][0]["agents"] = [actor("c4", 4)] + [actor(c, int(c[1]), "closed" if c != "c3" else "idle")
                                                             for c in ("c3", "c2", "c1")]
        new = self.given(avatars.assign(home))[("g", "c4")]
        self.assertNotEqual(hues[new], hues[got[("g", "c3")]])

    def test_once_every_picture_is_held_the_least_recently_given_comes_again(self):
        self.pictures({"robot/a": "red", "robot/b": "blue"})
        home = {"gatherers": [{"name": "g", "agents": [actor("c2", 2, "closed"), actor("c1", 1, "closed")]}]}
        got = self.given(avatars.assign(home))
        home["gatherers"][0]["agents"].insert(0, actor("c3", 3, "closed"))
        newest = got[("g", "c2")]                                             # given first: the least recent
        self.assertEqual(self.given(avatars.assign(home))[("g", "c3")], newest)

    def test_a_picture_taken_out_of_the_folder_is_replaced(self):
        self.pictures({"robot/a": "red", "robot/b": "blue"})
        home = {"gatherers": [{"name": "g", "agents": [actor("c1", 1)]}]}
        had = self.given(avatars.assign(home))[("g", "c1")]
        os.remove(avatars.path(had))
        self.assertEqual(self.given(avatars.attach(home, avatars.stored(), avatars.pictures()))[("g", "c1")], None)
        self.assertEqual(self.given(avatars.assign(home))[("g", "c1")], ({"robot/a", "robot/b"} - {had}).pop())
        os.remove(avatars.path(({"robot/a", "robot/b"} - {had}).pop()))
        os.rmdir(os.path.join(avatars.DIR, "robot"))
        self.assertEqual(self.given(avatars.assign(home))[("g", "c1")], None)   # none left: the harness's mark

    def test_the_drawn_avatars_are_in_one_hue_of_the_palette_each(self):
        avatars.DIR = self.saved[1]
        pool = avatars.pictures()
        self.assertGreaterEqual(len(pool), 100)
        hues = {"red", "orange", "yellow", "lime", "green", "teal", "sky", "blue", "purple", "pink", "brown", "gray"}
        self.assertEqual(set(pool.values()), hues)
        for name in pool:
            with open(avatars.path(name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertTrue(text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"'), name)
            self.assertIsNone(re.search(r"<script|href=|url\(|\bon\w+=", text), name)


class ServerAvatarsTest(AvatarsBase):
    def setUp(self):
        super().setUp()
        self.httpd = server.serve("127.0.0.1", 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def test_a_picture_is_served_with_no_scripts_and_nothing_else_is(self):
        self.pictures({"food/pear": "lime"})
        r = urllib.request.urlopen(self.url + "/avatars/food/pear.svg", timeout=10)
        self.assertEqual(r.headers["Content-Type"], "image/svg+xml")
        self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])
        self.assertIn(b'data-hue="lime"', r.read())
        with open(os.path.join(self.tmp.name, "secret.svg"), "w") as fh:
            fh.write("x")
        for path in ("/avatars/food/none.svg", "/avatars/../secret.svg", "/avatars/%2e%2e/secret.svg", "/avatars/food/pear.txt"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.url + path, timeout=10)
            self.assertEqual(caught.exception.code, 404, path)


if __name__ == "__main__":
    unittest.main()
