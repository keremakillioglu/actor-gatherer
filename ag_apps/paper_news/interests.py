"""What the user is interested in, for Paper news's agent to judge new papers by: what the user told the app
(`Inputs`), the structured summary the agent writes of it (`FIELDS`), and the messages the app sends the agent.

    FIELDS                  the summary's fields: (name, kind "text" | "list", label, what it holds)
    clean_inputs(d)         what the user told the app, checked: {scholar, keywords, topics, papers, notes}
    clean_profile(d)        a summary's fields, checked (missing ones empty)
    profile_text(fields)    a summary as the agent reads it
    summarize_message(...)  the agent asked to (re)write the summary: the user's inputs, the summary as it is (and
                            the fields the user wrote themselves), their feedback since
    judge_message(...)      the agent asked to pick a day's papers relevant to the user, the summary and the papers
                            (titles and abstracts) in it
    ASKED                   what each message starts with: "(Paper news · <where>: <what>)" -- where in the app it is
                            about (a day, "Your interests"), and what it asks, which Chat and the list show of it under
                            the app's mark (app.toml's [asked])"""

import re
from typing import Dict, Iterable, List, Optional

FIELDS = (
    ("summary", "text", "Research in brief",
     "Two to four sentences: what the user works on, and what they want from new papers."),
    ("core_topics", "list", "Core topics",
     "Topics at the centre of their work: a paper mainly about one of these is relevant."),
    ("related_topics", "list", "Related topics",
     "Topics they follow more loosely: relevant when a paper connects to their core work, or is a notable result."),
    ("methods", "list", "Methods and systems",
     "Methods, models, systems, datasets and benchmarks they build or use: a paper that improves, uses or evaluates one "
     "may be relevant."),
    ("followed_papers", "list", "Papers they follow",
     "Papers whose related work they want, as \"title (arXiv id)\": a paper that builds on, extends, competes with or "
     "evaluates against one is relevant."),
    ("followed_people", "list", "People and groups",
     "Authors and groups whose new papers they want to see."),
    ("keywords", "list", "Keywords",
     "Words and phrases that signal a relevant paper."),
    ("not_interested", "list", "Not interested in",
     "Topics and kinds of papers they don't want, even when one matches a keyword."),
    ("guidance", "text", "How to judge",
     "How strict to be and what makes a paper worth showing them (for example, systems papers over theory, or only "
     "papers with an evaluation), as their feedback shows."),
)
FIELD_NAMES = tuple(f[0] for f in FIELDS)
TEXT_CHARS, ITEM_CHARS, ITEMS_MAX = 2000, 300, 60
INPUT_ITEMS_MAX = 100
ABSTRACT_CHARS = 600            # of each abstract, in the agent's message: the rest with paper_news_paper
ASKED = "(Paper news · "


class InterestError(ValueError):
    """What the user or the agent gave can't be used: why."""


def _items(v, name: str, limit: int = ITEMS_MAX) -> List[str]:
    if isinstance(v, str):
        v = re.split(r"\n|;", v)
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise InterestError(f"{name}: a list of short texts")
    out = []
    for x in v:
        x = " ".join(x.split())[:ITEM_CHARS]
        if x and x not in out:
            out.append(x)
    return out[:limit]


def _text(v, name: str) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise InterestError(f"{name}: text")
    return v.strip()[:TEXT_CHARS]


def clean_inputs(d: dict) -> dict:
    """What the user told the app: their Google Scholar (or other) profile's address, keywords, topics, papers they
    want related work on (arXiv ids, links or titles, one a line), and anything else."""
    if not isinstance(d, dict):
        raise InterestError("a JSON object, please")
    scholar = _text(d.get("scholar"), "scholar")
    if scholar and not re.match(r"^https?://\S+$", scholar):
        raise InterestError("Your profile must be a web address, such as https://scholar.google.com/citations?user=...")
    keywords = d.get("keywords")
    if isinstance(keywords, str):
        keywords = re.split(r"[,\n;]", keywords)
    got = {"scholar": scholar, "keywords": _items(keywords, "keywords", INPUT_ITEMS_MAX),
           "topics": _items(d.get("topics"), "topics", INPUT_ITEMS_MAX),
           "papers": _items(d.get("papers"), "papers", INPUT_ITEMS_MAX), "notes": _text(d.get("notes"), "notes")}
    if not any(got.values()):
        raise InterestError("Fill in your profile, keywords, topics or papers.")
    return got


def clean_profile(d: dict, partial: bool = False) -> Dict[str, object]:
    """A summary's fields, each checked: text fields text, list fields lists of short texts. Missing ones are empty --
    or, `partial`, left out."""
    if not isinstance(d, dict):
        raise InterestError("the summary's fields, as an object")
    unknown = [k for k in d if k not in FIELD_NAMES]
    if unknown:
        raise InterestError(f"not a field of the summary: {', '.join(unknown)} (they are: {', '.join(FIELD_NAMES)})")
    out: Dict[str, object] = {}
    for name, kind, _, _ in FIELDS:
        if partial and name not in d:
            continue
        out[name] = _text(d.get(name), name) if kind == "text" else _items(d.get(name), name)
    return out


def profile_text(fields: dict) -> str:
    """The summary as the agent reads it: a line a field, lists "; "-joined; empty fields left out."""
    lines = []
    for name, kind, label, _ in FIELDS:
        v = fields.get(name)
        if v:
            lines.append(f"- {label}: {v if kind == 'text' else '; '.join(v)}")
    return "\n".join(lines) or "(empty)"


def inputs_text(inputs: dict) -> str:
    rows = []
    if inputs.get("scholar"):
        rows.append(f"- Their profile: {inputs['scholar']}")
    if inputs.get("keywords"):
        rows.append(f"- Keywords: {', '.join(inputs['keywords'])}")
    if inputs.get("topics"):
        rows.append("- Topics:\n" + "\n".join(f"  - {t}" for t in inputs["topics"]))
    if inputs.get("papers"):
        rows.append("- Papers they want related work on:\n" + "\n".join(f"  - {p}" for p in inputs["papers"]))
    if inputs.get("notes"):
        rows.append(f"- In their words: {inputs['notes']}")
    return "\n".join(rows)


def summarize_message(inputs: dict, profile: Optional[dict], edited: Iterable[str], feedback: List[dict],
                      why: str) -> str:
    """The agent asked to write the summary (`profile`, the one there is, if any; `edited`, its fields the user wrote
    themselves; `feedback`, the user's since it was written, each {verdict, title, id, picked, why})."""
    head = {"first": "write a summary of the user's research interests",
            "inputs": "write the summary of the user's interests again: they changed what they told the app",
            "feedback": f"update the summary of the user's interests from their last {len(feedback)} feedback"}[why]
    parts = [f"{ASKED}Your interests: {head})",
             "",
             "The Paper news app shows the user each weekday's new arXiv papers in their categories, and you pick the "
             "ones related to their research. You judge by a summary of their interests, which you write now with "
             "paper_news_profile.",
             "",
             "What the user told the app:",
             inputs_text(inputs)]
    if profile:
        parts += ["", "The summary as it is now:", profile_text(profile)]
        ed = [label for name, _, label, _ in FIELDS if name in set(edited)]
        if ed:
            parts += ["", f"The user wrote these fields themselves: {', '.join(ed)}. Keep what they wrote, adding to it "
                          "only what their feedback clearly shows."]
    if feedback:
        parts += ["", "Their feedback on papers since the summary was written (whether you had picked the paper, and "
                      "why):"]
        for f in feedback:
            said = "relevant" if f["verdict"] == "relevant" else "not relevant"
            had = f"you picked it: {f['why']}" if f.get("picked") else "you hadn't picked it"
            parts.append(f"- {said}: [{f['id']}] {f['title']} ({had})")
    parts += ["",
              "Look up what you need to understand their work: their profile page (if it won't load, go by the rest), "
              "and the papers they named (https://arxiv.org/abs/<id>, or search for a title). Then call paper_news_profile "
              "once with every field, written for judging whether a new paper is relevant to them: specific topics "
              "and methods rather than broad areas, and what they don't want in not_interested. "
              + ("Use their feedback: what they marked relevant that you hadn't picked, and what they marked not "
                 "relevant that you had, say most about where the summary was wrong. " if feedback else "")
              + "Don't change anything else. When it's saved, say in a sentence or two what changed."]
    return "\n".join(parts)


def judge_message(day_said: str, day: str, categories: List[str], profile: dict, papers: List[dict]) -> str:
    """The agent asked to pick `day`'s papers related to the user: the summary, then each paper's id, title,
    categories and abstract (cut at ABSTRACT_CHARS)."""
    parts = [f"{ASKED}{day_said}: pick the papers related to the user, of {len(papers)} new in {', '.join(categories)})",
             "",
             "The user's interests, as summarized:",
             profile_text(profile),
             "",
             f"The new papers of {day_said} in {', '.join(categories)}: each \"[id] title (categories)\", then its "
             f"abstract (cut at {ABSTRACT_CHARS} characters: paper_news_paper gives a whole one).",
             ""]
    for p in papers:
        ab = p["abstract"]
        if len(ab) > ABSTRACT_CHARS:
            ab = ab[:ABSTRACT_CHARS].rsplit(" ", 1)[0] + " …"
        parts += [f"[{p['id']}] {p['title']} ({'; '.join(p['categories'])})", ab, ""]
    parts += ["Decide which of these are relevant to the user, judging by the summary: most days only a few are, and "
              "none is fine. A paper is relevant when it is about their core topics, builds on or competes with the "
              "papers and methods they follow, or is by the people they follow; not when it only shares a broad area "
              "or a word. Then call paper_news_relevant once, with day \"" + day + "\" and every relevant paper: its id, a "
              "score (3: at the centre of their interests, 2: clearly related, 1: loosely related but worth a look) "
              "and why, in one line the user reads (what in the paper connects to what in their interests). With none "
              "relevant, call it with no picks. Read an abstract in full with paper_news_paper only when the cut one isn't "
              "enough to decide. Don't change the summary. Then say in a sentence how many you picked."]
    return "\n".join(parts)
