"""pi's launcher (ag/integrations/harnesses/pi/setup/launch.py): the extension for the run, unless pi's
settings install it."""

import json
import os
import unittest

from ag.integrations.harnesses.pi.setup import launch as pi
from cli_home import Home


class Pi(Home):
    def test_pi_gets_the_extension_for_the_run(self):
        code, out, err = self.run_ag("--dry-run", "pi", "-p", "hi")
        self.assertEqual(code, 0, err)
        self.assertIn(f"-e {pi.EXTENSION} --ag-gatherer default -p hi", out)         # the default gatherer
        self.assertIn("AG_ADAPTOR=" + os.path.join(pi.REPO, "ag/integrations/harnesses/pi/adaptor/adaptor.ts:PiAdaptor"),
                      out)                                                        # the adaptor ag checked


    def test_the_gatherer_by_its_flag(self):
        code, out, err = self.run_ag("--dry-run", "--gatherer", "demo", "pi", "-p", "hi")
        self.assertEqual(code, 0, err)
        self.assertIn(f"-e {pi.EXTENSION} --ag-gatherer demo -p hi", out)
        self.assertNotIn("AG_GATHERER", out)

    def test_one_gatherer_per_session(self):
        code, out, err = self.run_ag("--dry-run", "--gatherer", ".", "pi", "-p", "hi")
        self.assertEqual(code, 0, err)
        self.assertIn(f"-e {pi.EXTENSION} -p hi", out)                                # pi names it, by its session

    def test_installed_by_settings_means_no_e(self):
        agent = os.path.join(self.tmp, "agent")
        os.makedirs(agent)
        rel = os.path.relpath(pi.REPO, agent)
        with open(os.path.join(agent, "settings.json"), "w") as fh:
            json.dump({"packages": [rel, "npm:other"]}, fh)
        env = {"PI_CODING_AGENT_DIR": agent}
        self.assertEqual(pi.installed_in(self.tmp, env), os.path.join(agent, "settings.json"))
        self.assertEqual(pi.argv(["pi"], ["-p", "x"], self.tmp, env), ["pi", "-p", "x"])
        self.assertEqual(pi.argv(["pi"], ["-p", "x"], self.tmp, {"PI_CODING_AGENT_DIR": self.tmp}),
                         ["pi", "-e", pi.EXTENSION, "-p", "x"])
        self.assertEqual(pi.argv(["pi"], ["-p", "x"], self.tmp, env, "demo"), ["pi", "--ag-gatherer", "demo", "-p", "x"])
        self.assertEqual(pi.argv(["pi"], ["install", "npm:y"], self.tmp, env, "demo"), ["pi", "install", "npm:y"])
        self.assertEqual(pi.argv(["pi"], ["install", "npm:y"], self.tmp, {"PI_CODING_AGENT_DIR": self.tmp}),
                         ["pi", "install", "npm:y"])

if __name__ == "__main__":
    unittest.main()
