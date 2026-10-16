"""What the tests of ag (tests/test_cli.py, test_*_launch.py) share: a context
manager home, a codex home and a pi agent directory of their own -- never the
real ones, which may already install this clone -- and ag run in-process."""

import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from ag.cli import main


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "ag")
        self.codex_home = os.path.join(self.tmp, "codex")
        os.makedirs(self.codex_home)
        env = {"AG_HOME": self.home, "CODEX_HOME": self.codex_home,
               "PI_CODING_AGENT_DIR": os.path.join(self.tmp, "pi")}   # not the real pi's settings
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, path: str) -> str:
        with open(path) as fh:
            return fh.read()

    def run_ag(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main.main(list(argv))
        return code, out.getvalue(), err.getvalue()
