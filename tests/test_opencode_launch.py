"""opencode's launcher (ag/integrations/harnesses/opencode/setup/launch.py): the plugin for the run, merged
into any OPENCODE_CONFIG_CONTENT given."""

import json
import unittest

from ag.cli.launch import LaunchError
from ag.integrations.harnesses.opencode.setup import launch as opencode
from cli_home import Home


class Opencode(Home):
    def test_opencode_gets_the_plugin_for_the_run(self):
        code, out, err = self.run_ag("--dry-run", "opencode", "run", "hi")
        self.assertEqual(code, 0, err)
        self.assertIn("OPENCODE_CONFIG_CONTENT=", out)
        self.assertIn(opencode.PLUGIN, out)
        self.assertIn("ag/integrations/harnesses/opencode/adaptor/adaptor.ts:OpencodeAdaptor", out)   # AG_ADAPTOR


    def test_merged_into_a_config_given_and_not_twice(self):
        self.assertEqual(json.loads(opencode.config_content()), {"plugin": [opencode.PLUGIN]})
        merged = json.loads(opencode.config_content('{"model": "m", "plugin": ["a"]}'))
        self.assertEqual(merged, {"model": "m", "plugin": ["a", opencode.PLUGIN]})
        named = json.loads(opencode.config_content('{"plugin": ["a", "%s"]}' % opencode.PLUGIN, "demo"))
        self.assertEqual(named["plugin"], ["a", [opencode.PLUGIN, {"gatherer": "demo"}]])      # ag's, in place of the given
        again = json.loads(opencode.config_content(json.dumps({"plugin": [[opencode.PLUGIN, {"gatherer": "s"}]]})))
        self.assertEqual(len(again["plugin"]), 1)
        with self.assertRaises(LaunchError):
            opencode.config_content("{nope")

if __name__ == "__main__":
    unittest.main()
