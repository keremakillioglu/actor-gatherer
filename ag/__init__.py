"""The context manager: five packages, apart from the harnesses that use it (ag/integrations/).

    ag_interface/   the contract: events and types, the Policy and Poller bases, and what a
                    policy is given (GathererStore, Gatherers, Jobs)
    ag_harness/     what runs a policy: the manager, the store, the server, the home
    ag_tools/       what it runs policies with: model clients, tokenizers, the background worker
    ag_policies/    the policies, and the toolkit they compose
    ag_pollers/     the pollers
"""
