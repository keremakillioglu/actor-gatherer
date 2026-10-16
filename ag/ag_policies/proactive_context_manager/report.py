"""Looking at a gatherer from outside: what a bulk load analysed, what a read
adopted, what each read returned. Read-only; for drivers and measurements,
not for a policy."""

from typing import Optional

from ag.ag_interface import property_column
from ag.ag_interface.policy import TypeIds
from . import tables
from ..tools import channel, history
from ..tools.groups import Groups


def describe(conn, channel_id: Optional[str], groups: Optional[Groups] = None) -> dict:
    """The channel's history and latest build, in numbers: events and their
    tokens (of the given groups; default the standard ones), tasks, the
    build's status and timing, the sections the channel's last read adopted
    (name, tokens), and the size of the context a read gets from them.
    `conn` is the gatherer's store (ag.ag_interface.GathererStore), opened by the caller."""
    groups = groups or Groups()
    types = TypeIds.load(conn)
    rows = history.rows(conn, types, groups, channel_id)
    tasks = tables.tasks_for(conn, channel_id)
    build = tables.build_for(conn, channel_id)
    out = {"gatherer_id": conn.gatherer, "channel_id": channel_id,
           "events": len(rows), "trace_tokens": sum(r.tokens for r in rows),
           "tasks": len(tasks), "build": None}
    if build:
        last = conn.last_read(channel.of(channel_id))
        made_ids = [r.made_id for r in (last["refs"] if last else []) if r.made_id is not None]
        made = conn.made_items(made_ids)
        sections = [{"name": made[m][0], "tokens": made[m][2]} for m in made_ids]
        cut = build["open_from_row"]
        tail = [r for r in rows if cut and r.row_id >= cut]
        out["build"] = {
            "build_id": build["build_id"], "status": build["status"], "error": build["error"],
            "seconds": round((build["finished_at"] or build["started_at"]) - build["started_at"], 3),
            "through_row": build["through_row"], "open_from_row": cut,
            "ranked": len(build["ranking"]),
            "sections": sections,
            "sections_tokens": sum(s["tokens"] for s in sections),
            "tail_tokens": sum(r.tokens for r in tail), "tail_events": len(tail),
        }
        out["context_tokens"] = out["build"]["sections_tokens"] + out["build"]["tail_tokens"]
    else:
        out["context_tokens"] = out["trace_tokens"]
    return out


def reads(conn, channel_id: Optional[str]) -> list:
    """Every read the channel made, oldest first: when, the event it
    responded to (`row_id`), its basis (build), how many items and tokens it
    returned, and how many of those were made. `conn`: the gatherer's store."""
    out = []
    for read_id, at, row_id, basis in conn.execute(
            f"SELECT read_id, read_at, row_id, basis FROM _reads WHERE ifnull({property_column(channel.CHANNEL)}, '') = ? "
            "ORDER BY read_id", (channel_id or "",)):
        got = conn.execute("""
            SELECT ri.row_id, ri.made_id, i.tokens, m.tokens FROM _read_items ri
            LEFT JOIN events i ON i.row_id = ri.row_id
            LEFT JOIN _made_items m ON m.made_id = ri.made_id
            WHERE ri.read_id = ? ORDER BY ri.position""", (read_id,)).fetchall()
        out.append({"read_id": read_id, "at": at, "row_id": row_id, "basis": basis, "items": len(got),
                    "made_items": sum(1 for g in got if g[1] is not None),
                    "tokens": sum((g[2] or 0) if g[0] is not None else (g[3] or 0) for g in got)})
    return out
