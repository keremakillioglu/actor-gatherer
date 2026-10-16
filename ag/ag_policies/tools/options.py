"""A policy's config from the options the harness gives it (the catalog's,
then the gatherer's): its config class's fields, with the per-task models
defaulting to the LLM's own (`llm.model`)."""

from dataclasses import fields
from typing import Optional

MODELS = ("segment_model", "rank_model", "boundary_model")


def config_from(config_cls, options: Optional[dict], llm=None):
    """`config_cls(**options)`, the model fields it has defaulting to
    `llm.model`. Raises ValueError on an option it has no field for."""
    options = dict(options or {})
    names = {f.name for f in fields(config_cls)}
    unknown = sorted(set(options) - names)
    if unknown:
        raise ValueError(f"{config_cls.__name__} has no {', '.join(unknown)}")
    model = getattr(llm, "model", None)
    base = {m: model for m in MODELS if m in names} if model else {}
    return config_cls(**{**base, **options})
