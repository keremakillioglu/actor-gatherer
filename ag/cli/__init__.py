"""`ag`: run a harness with the context manager set up in it.

    ag claude                              Claude Code, with the context manager
    ag codex exec "fix the tests"          codex exec, with the context manager
    ag pi | ag opencode run "..."          pi, opencode, the same way
    ag codex                               file every thread into the gatherer `default` ([cli] gatherer)
    ag --gatherer demo codex                   file every thread into the named gatherer `demo`
    ag --gatherer demo codex resume <id>       resume in it: a named gatherer has to be named again on a resume,
                                           or the thread files into `default`
    ag --gatherer . codex                      each thread a new gatherer of its own, named by its id
    ag --gatherer demo --policy <policy> pi    ... made with this policy (and --poller X ... or --no-pollers)
    ag --dry-run codex exec "..."          print what would run, and run nothing

ag's own commands -- help, home, config, status, stop, gatherers, show, new, model --
are not harness names: a [cli.harnesses.<name>] named after one is refused.

Everything after the harness's name goes to the harness as it is. Nothing the
harness reads is changed: no config file of the harness is written, and
running it without `ag` behaves as before. What ag adds -- a flag, an
environment variable, a hook server its API calls go through -- is for that
run alone, and so is the gatherer it passes on; each harness's launcher
(ag/integrations/harnesses/<name>/setup/launch.py) says what it adds.
AG_GATHERER, which the setups fall back on when run by hand, is not passed on.

Every setting is in <home>/config.toml (AG_HOME, default ~/.ag): ag's are
its [cli] section, added with the defaults written out the first time ag
runs; the context manager's -- the default policy, the LLM the policies
call, the catalog of policies and pollers -- are its [policies] and
[pollers].

ag knows a harness only from its entry in config.toml,
[cli.harnesses.<name>], which names its launcher class and its adaptor class
(the ones this clone ships -- claude, codex, opencode, pi -- are in
ag/cli/harnesses.toml). `ag <name>` checks that the policy the run would use
takes every event type the adaptor and the gatherer's pollers output -- and
refuses to run otherwise -- then runs what the launcher returns, the adaptor
handed on to the harness's setup.
"""
