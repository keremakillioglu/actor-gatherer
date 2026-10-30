"""Claude Code's PreToolUse hook for a DocWriter actor (docwriter.py's `launch_args`): an edit of a file open in
DocWriter, by Claude Code's own tools, refused -- with why, and what to use instead (DocWriter's edit_doc, which
proposes the change for the author to accept). It asks the dashboard (`guard`, at the URL it is run with); a
dashboard it cannot reach, or any trouble, lets the edit go. Run as a script, standard library only:

    python docwriter_guard.py http://127.0.0.1:4200/docwriter/w/<key>/guard     (the tool call's JSON on stdin)
"""
import json
import sys
import urllib.request


def main() -> int:
    try:
        call = json.load(sys.stdin)
        given = call.get("tool_input") or {}
        path = given.get("file_path") or given.get("notebook_path") or ""
        if not path:
            return 0
        req = urllib.request.Request(sys.argv[1], data=json.dumps({"path": path}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as res:
            why = json.load(res).get("deny")
    except Exception:  # noqa: BLE001 - the edit is not held up by the hook's own trouble
        return 0
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
