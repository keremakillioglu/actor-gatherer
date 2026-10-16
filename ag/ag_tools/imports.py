"""Importing a callable named by a "module:attr" string, and calling one
with as many of the given arguments as it takes."""

import importlib
import inspect
import sys


def load_factory(spec: str, paths: list):
    """The attribute `attr` of module `module`, with each of `paths` put on
    sys.path first (in order)."""
    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)
    module, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module), attr)


def arity(fn) -> int:
    """How many positional arguments `fn` takes (a large number for *args)."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return 99
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return 99
    return len([p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])


def call(fn, *args):
    """`fn` called with the first of `args` it takes positionally: all of
    them if it takes *args, none if it takes none. So a factory can take
    the gatherer or not."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):                    # a builtin without a signature: give it all
        return fn(*args)
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return fn(*args)
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return fn(*args[:len(positional)])
