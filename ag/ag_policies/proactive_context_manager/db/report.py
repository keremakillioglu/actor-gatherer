"""Looking at a gatherer from outside: what a bulk load built, what a read
adopted, what each read returned. Read-only; for drivers and measurements,
not for a policy."""

from typing import Optional

from ag.ag_interface import property_column
from ag.ag_interface.policy import TypeIds
from . import tables
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools.groups import Groups


def describe(conn, channel_id: Optional[str], groups: Optional[Groups] = None) -> dict:
    """The channel's history and latest build, in numbers: events and their
    tokens (of the given groups; default the standard ones), tasks, the
    build's status and timing, the sections the channel's last read adopted
    (name, tokens), and the size of the context a read gets from them.
    `conn` is the gatherer's store (ag.ag_interface.GathererStore), opened by the caller."""
    groups = groups or Groups()
    types = TypeIds.load(conn)
    rows = history.rows(conn, types, groups, channel_id)
    tasks = tables.get_tasks(conn, channel_id)
    build = tables.get_latest_build(conn, channel_id)
    out = {"gatherer_id": conn.gatherer, "channel_id": channel_id,
           "events": len(rows), "trace_tokens": sum(row.tokens for row in rows),
           "tasks": len(tasks), "build": None}
    if build:
        last_read = conn.last_read(channel.of(channel_id))
        made_ids = [ref.made_id for ref in (last_read["refs"] if last_read else []) if ref.made_id is not None]
        items_by_id = conn.made_items(made_ids)
        sections = [{"name": items_by_id[made_id][0], "tokens": items_by_id[made_id][2]} for made_id in made_ids]
        verbatim_start = build["open_from_row"]
        verbatim_rows = [row for row in rows if verbatim_start and row.row_id >= verbatim_start]
        out["build"] = {
            "build_id": build["build_id"], "status": build["status"], "error": build["error"],
            "seconds": round((build["finished_at"] or build["started_at"]) - build["started_at"], 3),
            "through_row": build["through_row"], "open_from_row": verbatim_start,
            "ranked": len(build["ranking"]),
            "sections": sections,
            "sections_tokens": sum(section["tokens"] for section in sections),
            "tail_tokens": sum(row.tokens for row in verbatim_rows), "tail_events": len(verbatim_rows),
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
    for read_id, read_at, row_id, basis in conn.execute(
            f"SELECT read_id, read_at, row_id, basis FROM _reads WHERE ifnull({property_column(channel.CHANNEL)}, '') = ? "
            "ORDER BY read_id", (channel_id or "",)):
        items = conn.execute("""
            SELECT ri.row_id, ri.made_id, i.tokens, m.tokens FROM _read_items ri
            LEFT JOIN events i ON i.row_id = ri.row_id
            LEFT JOIN _made_items m ON m.made_id = ri.made_id
            WHERE ri.read_id = ? ORDER BY ri.position""", (read_id,)).fetchall()
        out.append({"read_id": read_id, "at": read_at, "row_id": row_id, "basis": basis, "items": len(items),
                    "made_items": sum(1 for item in items if item[1] is not None),
                    "tokens": sum((item[2] or 0) if item[0] is not None else (item[3] or 0) for item in items)})
    return out
