"""What the context manager's harness runs its policies with -- services it
gives them, and helpers -- apart from the harness itself:

    llm/          model clients: LiteLLMClient (any provider, through LiteLLM), CLIClient
                  (a coding agent's CLI, on its login)
    tokenizers/   token counters: Tiktoken (the default), LiteLLM
    worker.py     a policy's background jobs: WorkerJobs (ag.ag_interface.Jobs) starts `python -m
                  ag.ag_tools.worker`, which gets the policy from a factory and runs its job
    imports.py    load_factory(): a callable from a "module:attr" string
    log.py        warn(): a line to stderr

It imports ag.ag_interface and nothing else of the context manager: the harness
(ag.ag_harness) imports it, and hands what it makes to the policies.
"""
