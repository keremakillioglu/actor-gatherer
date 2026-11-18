"""app_kit/installing.py: an app staged from a folder or a git URL, installed into <home>/apps, updated, uninstalled
(its data/ kept unless asked), and the apps that come with ag uninstalled through config.toml's `[apps] removed` --
what `finding` then finds."""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app_kit import finding, installing  # noqa: E402
from app_kit.installing import InstallError  # noqa: E402

MANIFEST = textwrap.dedent('''
    name = "{name}"
    label = "Pager"
    version = "{version}"
    description = "pages you"

    [[tools]]
    name = "page"
    description = "Page the user."
    input_schema = {{ type = "object" }}
    handled_by = "panel"

    [panel]
    entry = "panel/index.html"
''')


def write_app(folder: str, name: str = "pager", version: str = "1") -> str:
    os.makedirs(os.path.join(folder, "panel"), exist_ok=True)
    with open(os.path.join(folder, "app.toml"), "w") as fh:
        fh.write(MANIFEST.format(name=name, version=version))
    with open(os.path.join(folder, "panel", "index.html"), "w") as fh:
        fh.write("<p>pager</p>")
    return folder


def git(*args: str, cwd: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


class InstallingBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._path = os.environ.pop(finding.PATH_ENV, None)
        self.addCleanup(lambda: self._path is not None and os.environ.__setitem__(finding.PATH_ENV, self._path))

    def found(self):
        return set(finding.find(self.home)[0])

    def config(self) -> str:
        with open(os.path.join(self.home, "config.toml")) as fh:
            return fh.read()


class FromAFolderTest(InstallingBase):
    def test_staged_then_installed_it_is_found_and_says_where_it_came_from(self):
        src = write_app(os.path.join(self.tmp, "src"))
        os.makedirs(os.path.join(src, "data"))                                 # its author's own files: not copied
        st = installing.stage(self.home, src)
        self.assertEqual((st.manifest.name, st.source["kind"]), ("pager", "folder"))
        self.assertFalse(os.path.exists(os.path.join(st.folder, "data")))
        self.assertNotIn("pager", self.found())                                # staged is not installed
        m = installing.install(self.home, st.id)
        self.assertEqual(m.folder, os.path.join(self.home, "apps", "pager"))
        self.assertIn("pager", self.found())
        self.assertEqual(installing.source(m.folder)["source"], os.path.realpath(src))
        self.assertFalse(os.path.exists(st.folder))                            # out of staging

    def test_a_bad_manifest_is_refused_at_once_and_nothing_is_left_staged(self):
        src = write_app(os.path.join(self.tmp, "src"))
        with open(os.path.join(src, "app.toml"), "a") as fh:
            fh.write('\npanels = "x"\n')
        with self.assertRaises(InstallError) as got:
            installing.stage(self.home, src)
        self.assertIn("app.toml", str(got.exception))
        self.assertEqual(os.listdir(os.path.join(self.home, "apps", installing.INCOMING)), [])

    def test_a_folder_that_is_not_an_app_or_not_there_is_refused(self):
        os.makedirs(os.path.join(self.tmp, "empty"))
        for where in (os.path.join(self.tmp, "empty"), os.path.join(self.tmp, "nope"), ""):
            with self.assertRaises(InstallError):
                installing.stage(self.home, where)

    def test_installed_twice_is_refused_but_an_update_replaces_it_keeping_its_data(self):
        src = write_app(os.path.join(self.tmp, "src"))
        m = installing.install(self.home, installing.stage(self.home, src).id)
        os.makedirs(os.path.join(m.folder, "data"))
        with open(os.path.join(m.folder, "data", "kept.txt"), "w") as fh:
            fh.write("mine")
        with open(os.path.join(m.folder, "old.txt"), "w") as fh:
            fh.write("gone after an update")
        again = installing.stage(self.home, write_app(src, version="2"))
        with self.assertRaises(InstallError):
            installing.install(self.home, again.id)
        self.assertEqual(installing.install(self.home, again.id, update=True).version, "2")
        self.assertTrue(os.path.isfile(os.path.join(m.folder, "data", "kept.txt")))
        self.assertFalse(os.path.exists(os.path.join(m.folder, "old.txt")))

    def test_the_name_of_an_app_that_comes_with_ag_is_refused(self):
        st = installing.stage(self.home, write_app(os.path.join(self.tmp, "src"), name="notes"))
        with self.assertRaises(InstallError) as got:
            installing.install(self.home, st.id)
        self.assertIn("comes with ag", str(got.exception))

    def test_discarded_it_is_gone_and_can_no_longer_be_installed(self):
        st = installing.stage(self.home, write_app(os.path.join(self.tmp, "src")))
        installing.discard(self.home, st.id)
        with self.assertRaises(InstallError):
            installing.install(self.home, st.id)
        with self.assertRaises(InstallError):
            installing.staged(self.home, "../../etc")


class FromGitTest(InstallingBase):
    def setUp(self):
        super().setUp()
        if shutil.which("git") is None:
            self.skipTest("no git")
        self.repo = write_app(os.path.join(self.tmp, "repo"))
        git("init", "-q", cwd=self.repo)
        git("add", ".", cwd=self.repo)
        git("commit", "-qm", "first", cwd=self.repo)
        self.url = "file://" + self.repo

    def test_cloned_at_its_newest_commit_without_its_history(self):
        st = installing.stage(self.home, self.url)
        head = git("rev-parse", "HEAD", cwd=self.repo)
        self.assertEqual(st.source, {"kind": "git", "source": self.url, "commit": head})
        self.assertFalse(os.path.exists(os.path.join(st.folder, ".git")))
        self.assertEqual(installing.latest(self.url), head)
        m = installing.install(self.home, st.id)
        self.assertEqual(installing.source(m.folder)["commit"], head)

    def test_a_url_git_cannot_clone_is_refused_with_git_s_words(self):
        with self.assertRaises(InstallError) as got:
            installing.stage(self.home, "file://" + os.path.join(self.tmp, "nowhere"))
        self.assertIn("couldn't clone", str(got.exception))
        self.assertIsNone(installing.latest("file://" + os.path.join(self.tmp, "nowhere")))

    def test_what_counts_as_a_git_url(self):
        self.assertEqual(installing.git_url("github.com/a/b"), "https://github.com/a/b")
        for url in ("https://example.org/a/b", "git@github.com:a/b.git", "ssh://h/a", "file:///x/y"):
            self.assertEqual(installing.git_url(url), url)
        self.assertIsNone(installing.git_url(self.repo))                       # a folder: copied, not cloned


class UninstallTest(InstallingBase):
    def test_an_installed_app_s_folder_goes_but_its_data_stays_unless_asked(self):
        src = write_app(os.path.join(self.tmp, "src"))
        m = installing.install(self.home, installing.stage(self.home, src).id)
        os.makedirs(os.path.join(m.folder, "data"))
        self.assertEqual(installing.uninstall(self.home, "pager", m.folder), "home")
        self.assertNotIn("pager", self.found())
        self.assertEqual(os.listdir(m.folder), ["data"])
        m = installing.install(self.home, installing.stage(self.home, src).id)   # back, beside its data
        self.assertTrue(os.path.isdir(os.path.join(m.folder, "data")))
        installing.uninstall(self.home, "pager", m.folder, data=True)
        self.assertFalse(os.path.exists(m.folder))

    def test_an_app_that_comes_with_ag_is_named_in_config_toml_and_comes_back_when_restored(self):
        with open(os.path.join(self.home, "config.toml"), "w") as fh:
            fh.write('# mine\n[dashboard]\nport = 4200   # kept\n')
        notes = finding.find(self.home)[0]["notes"]
        os.makedirs(os.path.join(self.home, "apps", "notes", "data"))
        self.assertEqual(installing.uninstall(self.home, "notes", notes.folder), "builtin")
        self.assertNotIn("notes", self.found())
        self.assertIn("# mine\n[dashboard]\nport = 4200   # kept\n", self.config())
        self.assertEqual(finding.removed(self.home), ["notes"])
        self.assertTrue(os.path.isdir(os.path.join(self.home, "apps", "notes", "data")))   # its data kept
        installing.restore(self.home, "notes")
        self.assertIn("notes", self.found())
        self.assertEqual(finding.removed(self.home), [])
        with self.assertRaises(InstallError):
            installing.restore(self.home, "pager")

    def test_one_from_ag_apps_path_is_removed_there(self):
        path = os.path.join(self.tmp, "mine")
        write_app(os.path.join(path, "pager"))
        os.environ[finding.PATH_ENV] = path
        self.addCleanup(os.environ.pop, finding.PATH_ENV, None)
        with self.assertRaises(InstallError) as got:
            installing.uninstall(self.home, "pager", os.path.join(path, "pager"))
        self.assertIn("AG_APPS_PATH", str(got.exception))


class RemovedListTest(InstallingBase):
    def removed(self):
        with open(os.path.join(self.home, "config.toml"), "rb") as fh:
            return tomllib.load(fh)["apps"]

    def test_written_into_a_config_toml_with_or_without_an_apps_table(self):
        installing.set_removed(self.home, ["slack"])                             # none yet
        self.assertEqual(self.removed(), {"removed": ["slack"]})
        with open(os.path.join(self.home, "config.toml"), "w") as fh:
            fh.write('[apps]\nindex = ["x"]\n\n[pollers]\ndefault = []\n')
        installing.set_removed(self.home, ["slack", "notes"])
        self.assertEqual(self.removed(), {"index": ["x"], "removed": ["slack", "notes"]})
        installing.set_removed(self.home, [])
        self.assertEqual(self.removed(), {"index": ["x"], "removed": []})
        self.assertIn("[pollers]\ndefault = []", self.config())

    def test_a_removed_list_written_over_several_lines_is_not_rewritten(self):
        with open(os.path.join(self.home, "config.toml"), "w") as fh:
            fh.write('[apps]\nremoved = [\n  "slack",\n]\n')
        with self.assertRaises(InstallError):
            installing.set_removed(self.home, ["slack", "notes"])
        self.assertEqual(self.removed(), {"removed": ["slack"]})                 # untouched


class IndexTest(unittest.TestCase):
    def test_ag_s_index_reads_and_starts_empty(self):
        self.assertEqual(installing.index(), [])


if __name__ == "__main__":
    unittest.main()
