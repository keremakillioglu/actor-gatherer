"""setup_home.py <ag> <your config.toml> <scratch AG_HOME>: a scratch ag home for the demo, so your own is left
as it is. It gets the Gatherer's LLM from your config ([policies.llm]); everything else is ag's default."""
import os, subprocess, sys, tomllib

ag, yours, home = sys.argv[1:4]
llm = tomllib.load(open(yours, "rb")).get("policies", {}).get("llm", {})
if not llm.get("model"):
    sys.exit(f"no Gatherer LLM in {yours}: set one with `ag model provider/model` first")
args = [llm["model"]]
if llm.get("api_base"):
    args += ["--api-base", llm["api_base"]]
if llm.get("key_env"):
    args += ["--key-env", llm["key_env"]]
subprocess.run([*ag.split(), "model", *args], check=True, stdout=subprocess.DEVNULL,
               env={**os.environ, "AG_HOME": home})
