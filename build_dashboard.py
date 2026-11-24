"""
Build a self-contained dashboard (dashboard.html) from the prioritizer output.
GE2340 Course Project - AI-Powered Student Daily Prioritizer & Noise Filter

Usage:
    python build_dashboard.py                                   # results.csv + announcements.csv
    python build_dashboard.py results.csv sample_announcements.csv

If announcements.csv does not exist, sample_announcements.csv is used.
Only the Python standard library is used. The generated HTML has no external
resources (no CDNs, fonts or network calls): the data never leaves this machine.

Demo tips (URL parameters when opening dashboard.html):
    dashboard.html?date=2026-11-29     open "viewing as" a given day
    dashboard.html?open=003            open one message expanded
"""

import ast
import base64
import csv
import glob
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = "dashboard.html"
PRIORITIZER_FILE = os.path.join(HERE, "prioritizer.py")

# Fallbacks, used only if the constants cannot be read from prioritizer.py
DEFAULT_RULES = {
    "short_window_hours": 48,
    "medium_window_hours": 7 * 24,
    "reference_hour": 9,
    "matrix": {
        "Low":    ["Medium", "Low",    "Low"],
        "Medium": ["High",   "Medium", "Medium"],
        "High":   ["Urgent", "High",   "High"],
    },
    "source": "built-in defaults",
}


# ---------------------------------------------------------------------------
# Read the priority rule from prioritizer.py (without importing it, so no
# API libraries are needed) to keep dashboard and prioritizer in sync.
# ---------------------------------------------------------------------------
def _timedelta_hours(node):
    """Hours in an expression like timedelta(hours=48) or timedelta(days=7)."""
    if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "timedelta"):
        raise ValueError("not a timedelta(...) call")
    factors = {"weeks": 168, "days": 24, "hours": 1, "minutes": 1 / 60, "seconds": 1 / 3600}
    return sum(factors[kw.arg] * ast.literal_eval(kw.value) for kw in node.keywords)


def load_rules(path=PRIORITIZER_FILE):
    rules = dict(DEFAULT_RULES)
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                found[node.targets[0].id] = node.value
        rules = {
            "short_window_hours": _timedelta_hours(found["SHORT_WINDOW"]),
            "medium_window_hours": _timedelta_hours(found["MEDIUM_WINDOW"]),
            "reference_hour": ast.literal_eval(found.get("REFERENCE_HOUR", ast.Constant(9))),
            "matrix": {k: list(v) for k, v in ast.literal_eval(found["PRIORITY_MATRIX"]).items()},
            "source": "prioritizer.py",
            "model": ast.literal_eval(found["MODEL"]) if "MODEL" in found else "",
        }
    except (OSError, KeyError, ValueError, SyntaxError) as e:
        print(f"Note: could not read rules from prioritizer.py ({e}); using built-in defaults.")
    return rules


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------
def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
        return rows, [c.strip() for c in (reader.fieldnames or [])]


def id_key(value):
    """'001' and '1' should match."""
    value = (value or "").strip()
    return value.lstrip("0") or value


def parse_bool(value):
    """'True'/'False' from the CSV -> True/False; anything else (empty, INVALID) -> None."""
    value = (value or "").strip().lower()
    if value in ("true", "yes", "1"):
        return True
    if value in ("false", "no", "0"):
        return False
    return None


def load_eval(results_path):
    """Numbers from evaluate.py (results/eval/summary.csv) and its confusion matrices, if present."""
    eval_dir = os.path.join(os.path.dirname(os.path.abspath(results_path)), "eval")
    summary = os.path.join(eval_dir, "summary.csv")
    if not os.path.exists(summary):
        return None
    rows, _ = read_csv(summary)
    runs = []
    for r in rows:
        run = next((x for x in runs if x["name"] == r["run"]), None)
        if run is None:
            run = {"name": r["run"]}
            runs.append(run)
        run[r["subset"]] = r
    images = []
    for png in sorted(glob.glob(os.path.join(eval_dir, "confusion_*.png"))):
        with open(png, "rb") as f:
            images.append("data:image/png;base64," + base64.b64encode(f.read()).decode("ascii"))
    for run, img in zip(runs, images):
        run["confusion"] = img
    return {"runs": runs}


def load_profile_copy(results_path):
    """The profile saved next to the results by prioritizer.py (<stem>_profile.json), if any."""
    path = os.path.splitext(os.path.abspath(results_path))[0] + "_profile.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build_messages(results, announcements):
    bodies = {id_key(a.get("id")): a for a in announcements}
    messages = []
    for r in results:
        original = bodies.get(id_key(r.get("id")), {})
        messages.append({
            "id": r.get("id", ""),
            "source": r.get("source") or original.get("source", ""),
            "subject": r.get("subject") or original.get("subject", "") or "(no subject)",
            "received": original.get("date_received", ""),
            "body": original.get("body", ""),
            "stored_priority": r.get("final_priority") or r.get("ai_priority") or "",
            "importance": r.get("ai_importance", ""),
            "llm_priority": r.get("ai_llm_priority") or r.get("ai_priority", ""),
            "deadline": r.get("ai_deadline", ""),
            "task": r.get("ai_task", ""),
            "action": r.get("ai_suggested_action", ""),
            "evidence": r.get("ai_evidence", ""),
            "reference_date": r.get("reference_date", ""),
            "relevant": parse_bool(r.get("ai_relevant_to_user")),
            "relevance_reason": r.get("ai_relevance_reason", ""),
        })
    return messages


def main():
    results_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results.csv")
    if len(sys.argv) > 2:
        announcements_path = sys.argv[2]
    else:
        announcements_path = os.path.join(HERE, "announcements.csv")
        if not os.path.exists(announcements_path):
            announcements_path = os.path.join(HERE, "sample_announcements.csv")

    results, result_columns = read_csv(results_path)
    try:
        announcements, _ = read_csv(announcements_path)
    except OSError:
        print(f"Warning: {announcements_path} not found - original texts will be missing.")
        announcements = []

    if not results:
        sys.exit(f"Error: {results_path} has no rows.")

    rules = load_rules()
    can_recompute = "ai_importance" in result_columns and "ai_deadline" in result_columns
    config = {
        "rules": rules,
        "canRecompute": can_recompute,
        "resultsFile": os.path.basename(results_path),
        "announcementsFile": os.path.basename(announcements_path),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "eval": load_eval(results_path),
        "profile": load_profile_copy(results_path),
    }
    data = build_messages(results, announcements)

    def embed(obj):
        # Safe inside <script>: prevent "</script>" from closing the tag early
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    html = TEMPLATE.replace("__CONFIG__", embed(config)).replace("__DATA__", embed(data))
    out_path = os.path.join(os.path.dirname(os.path.abspath(results_path)), OUTPUT_FILE)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    unmatched = sum(1 for m in data if not m["body"])
    print(f"Built {out_path}")
    print(f"  {len(data)} messages from {os.path.basename(results_path)}, "
          f"texts from {os.path.basename(announcements_path)}"
          + (f" ({unmatched} without original text)" if unmatched else ""))
    print(f"  Date preview: {'on' if can_recompute else 'off (old results.csv format)'}; "
          f"rules from {rules['source']}")


# ---------------------------------------------------------------------------
# HTML template (placeholders: __CONFIG__, __DATA__)
# ---------------------------------------------------------------------------
TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Prioritizer</title>
<style>
  :root {
    --bg: #FAF7F0;          /* cream page */
    --surface: #FFFFFF;     /* panels */
    --line: #ECE6DA;        /* subtle borders */
    --hover: #FBF8F2;       /* row hover (secondary text keeps AA) */
    --inset: #FAF7F0;       /* original-text box inside panels */
    --ink: #2A2D33;
    --ink-2: #6B6F76;       /* secondary text: 4.7:1 on cream, 5.0:1 on white */
    --accent: #2F6F73;      /* links, focus, picker, buttons */
    --accent-soft: #E8F0EF;
    --urgent: #B42318;
    --high: #9A6000;        /* text; #B26B00 is too light for AA text */
    --high-dot: #B26B00;
    --medium: #2F6F73;
    --low: #9A9EA5;         /* markers only (not text) */
    --mark: #FFF1C2;
    --radius: 8px;
    --sans: -apple-system, "Segoe UI", system-ui, sans-serif;
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.55 var(--sans); -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
  }
  .wrap { max-width: 760px; margin: 0 auto; padding: 28px 24px 80px; }
  button { font: inherit; color: inherit; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }

  /* ---------- top bar ---------- */
  .topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px 16px; flex-wrap: wrap; }
  .brand { font-weight: 600; font-size: 15px; color: var(--ink); }
  .viewas { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-2); }
  .viewas input {
    font: 500 13px/1 var(--sans); color: var(--ink); background: var(--surface); border: 1px solid var(--line);
    border-radius: 6px; padding: 0 10px; height: 34px; accent-color: var(--accent);
  }
  .viewas input:hover:not(:disabled) { border-color: #D9D1C2; }
  .viewas input:disabled { color: var(--ink-2); background: transparent; }
  .chip-btn {
    border: 1px solid var(--accent); background: var(--surface); color: var(--accent); border-radius: 6px;
    padding: 0 14px; height: 34px; cursor: pointer; font-size: 13px; font-weight: 500;
    transition: background .15s ease, color .15s ease;
  }
  .chip-btn:hover:not(:disabled) { background: var(--accent-soft); }
  .chip-btn[aria-pressed="true"] { background: var(--accent); color: #fff; }
  .chip-btn:disabled { border-color: var(--line); color: var(--ink-2); cursor: default; }
  .date-note { flex-basis: 100%; margin: 0; font-size: 13px; color: var(--accent); text-align: right; }
  .date-note:empty { display: none; }

  /* ---------- greeting + summary ---------- */
  .hello { margin: 36px 0 0; }
  .hello h1 { font: 600 clamp(28px, 5vw, 36px)/1.2 var(--sans); letter-spacing: -0.02em; margin: 0 0 6px; }
  .dateline { color: var(--ink-2); margin: 0; }
  .stats { list-style: none; padding: 0; margin: 28px 0 0; display: grid; grid-template-columns: repeat(3, 1fr);
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
  .stats li { padding: 16px 18px; display: flex; flex-direction: column; gap: 2px; color: var(--ink-2); font-size: 13px; }
  .stats li + li { border-left: 1px solid var(--line); }
  .stats strong { font: 600 26px/1.2 var(--sans); letter-spacing: -0.02em; font-variant-numeric: tabular-nums; color: var(--ink); }
  .stats .s-urgent strong { color: var(--urgent); }

  /* ---------- groups ---------- */
  .group { margin-top: 48px; }
  .group-head { display: flex; align-items: baseline; gap: 8px; margin: 0 0 12px; }
  .group-head h2 { font-size: 16px; font-weight: 600; margin: 0; }
  .group-head .count { color: var(--ink-2); font-size: 14px; font-variant-numeric: tabular-nums; }
  .group-head .desc { color: var(--ink-2); font-size: 13px; margin-left: auto; text-align: right; }
  .list { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
  .list > .item + .item { border-top: 1px solid var(--line); }

  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; display: inline-block; margin-top: 8px; }
  .g-Urgent .dot { background: var(--urgent); }
  .g-High .dot { background: var(--high-dot); }
  .g-Medium .dot { background: var(--medium); }
  .g-Low .dot, .g-Expired .dot { background: var(--low); }

  /* row */
  .item-head {
    display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; gap: 2px 14px; align-items: start;
    width: 100%; text-align: left; background: none; border: 0; padding: 16px 18px; cursor: pointer;
    transition: background .15s ease;
  }
  .item-head:hover { background: var(--hover); }
  .item-head:focus-visible { outline-offset: -2px; border-radius: var(--radius); }
  .subject { display: block; font-weight: 600; font-size: 17px; line-height: 1.4; }
  .meta { display: block; color: var(--ink-2); font-size: 13px; margin-top: 2px; }
  .lines { display: block; margin-top: 8px; font-size: 14.5px; color: var(--ink); }
  .lines span { display: block; }
  .lines b { font-weight: 500; color: var(--ink-2); }
  .countdown { font-size: 14px; color: var(--ink-2); white-space: nowrap; font-variant-numeric: tabular-nums; padding-top: 2px; }
  .countdown.soon { font-weight: 600; }
  .g-Urgent .countdown.soon { color: var(--urgent); }
  .g-High .countdown.soon { color: var(--high); }
  .g-Medium .countdown.soon { color: var(--medium); }
  .chev { width: 18px; height: 18px; margin-top: 3px; color: var(--ink-2); transition: transform .2s ease; }
  [aria-expanded="true"] .chev { transform: rotate(180deg); }

  .detail { padding: 0 18px 18px 40px; }
  .detail[hidden] { display: none; }
  .detail.reveal { animation: reveal .22s ease-out; }
  @keyframes reveal { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
  .original {
    background: var(--inset); border: 1px solid var(--line); border-radius: 6px; padding: 14px 16px; white-space: pre-wrap;
    font-size: 14.5px; line-height: 1.65; color: var(--ink); margin: 0;
  }
  .original-label { font-size: 13px; color: var(--ink-2); margin: 4px 0 8px; }
  mark { background: var(--mark); color: var(--ink); border-radius: 3px; padding: 1px 2px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
  .why { display: flex; flex-wrap: wrap; gap: 4px 18px; margin: 12px 0 0; padding: 0; list-style: none; font-size: 13px; color: var(--ink-2); }
  .why b { color: var(--ink); font-weight: 500; }
  .evidence-miss { font-size: 13px; color: var(--ink-2); margin: 8px 0 0; }

  /* ---------- "Needs your attention now": clearest, but calm ---------- */
  .g-Urgent .group-head h2 { font-size: 19px; }
  .g-Urgent .item { box-shadow: inset 4px 0 0 var(--urgent); }
  .g-Urgent .item-head { padding: 20px 20px 20px 22px; }
  .g-Urgent .subject { font-size: 19px; }
  .g-Urgent .countdown { font-size: 15px; }
  .g-Urgent .detail { padding-left: 44px; }
  .calm {
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
    padding: 16px 18px; color: var(--ink-2); font-size: 14.5px;
  }

  /* ---------- collapsed, toned-down groups ---------- */
  .fold { margin-top: 0; border-top: 1px solid var(--line); }
  .group + .fold { margin-top: 48px; }
  .fold + .fold { margin-top: 0; }
  .fold:last-child { border-bottom: 1px solid var(--line); }
  .fold > summary {
    list-style: none; cursor: pointer; display: flex; align-items: center; gap: 6px;
    padding: 14px 4px; color: var(--ink-2); border-radius: 6px; transition: background .15s ease;
  }
  .fold > summary:hover { background: rgba(255,255,255,.6); }
  .fold > summary::-webkit-details-marker { display: none; }
  .fold > summary h2 { font-size: 14.5px; font-weight: 500; margin: 0; }
  .fold > summary .count { font-size: 14.5px; font-variant-numeric: tabular-nums; }
  .fold > summary .desc { font-size: 13px; margin-left: auto; text-align: right; }
  .fold > summary .chev { margin: 0 0 0 8px; }
  .fold[open] > summary .chev { transform: rotate(180deg); }
  .fold .list { margin: 2px 0 16px; }
  .fold .subject { font-weight: 500; font-size: 15px; color: var(--ink-2); }
  .notrel { display: block; font-size: 13px; color: var(--ink-2); margin-top: 4px; }
  .notrel b { font-weight: 600; color: var(--ink); }
  .fold .item-head { padding: 12px 18px; }


  /* ---------- project header + tabs ---------- */
  .project { margin-bottom: 18px; }
  .kicker { margin: 0; font-size: 12.5px; color: var(--ink-2); letter-spacing: .02em; }
  .project .brand { margin: 2px 0 0; font-size: 17px; }
  .tabs { display: flex; gap: 4px; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 3px; }
  .tabs a { padding: 6px 12px; border-radius: 6px; font-size: 13.5px; font-weight: 500; color: var(--ink-2); text-decoration: none; }
  .tabs a:hover { color: var(--ink); background: var(--hover); }
  .tabs a[aria-current="page"] { background: var(--accent); color: #fff; }
  .view[hidden] { display: none; }

  /* ---------- How it works / Evaluation ---------- */
  .block { margin-top: 40px; }
  .page-title { font: 600 clamp(26px, 4.6vw, 32px)/1.2 var(--sans); letter-spacing: -0.02em; margin: 0 0 10px; }
  .block h2 { font-size: 16px; font-weight: 600; margin: 0 0 10px; }
  .lead { margin: 0; max-width: 66ch; }
  .sub { margin: 0 0 12px; color: var(--ink-2); font-size: 13.5px; max-width: 70ch; }
  .io { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 18px 0 0; }
  .io div, .card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px; }
  .io dt { font-size: 12.5px; color: var(--ink-2); font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
  .io dd { margin: 4px 0 0; font-size: 14px; }

  .pipeline { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(4, 1fr); gap: 22px; counter-reset: step; }
  .pipeline li { position: relative; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px; font-size: 13.5px; }
  .pipeline li + li::before { content: "\2192"; position: absolute; left: -18px; top: 50%; transform: translateY(-50%); color: var(--ink-2); }
  .pipeline .num { display: inline-block; font-size: 12px; font-weight: 600; color: var(--accent); }
  .pipeline h3 { font-size: 14.5px; margin: 2px 0 6px; }
  .pipeline p { margin: 0; color: var(--ink-2); }
  .pipeline li.ai { border-color: var(--accent); box-shadow: inset 0 3px 0 var(--accent); }

  .table-wrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); font-size: 14px; }
  th, td { padding: 10px 12px; text-align: left; border-top: 1px solid var(--line); }
  thead th { border-top: 0; font-size: 12.5px; color: var(--ink-2); font-weight: 600; }
  tbody th { font-weight: 500; }
  .num-cell { font-variant-numeric: tabular-nums; white-space: nowrap; }
  .pri { display: inline-flex; align-items: center; gap: 6px; }
  .pri::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--low); }
  .pri.p-Urgent::before { background: var(--urgent); }
  .pri.p-High::before { background: var(--high-dot); }
  .pri.p-Medium::before { background: var(--medium); }

  .pick-label { display: block; font-size: 13px; color: var(--ink-2); margin-bottom: 6px; }
  select { font: 14px var(--sans); color: var(--ink); background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; width: 100%; max-width: 100%; }
  .trace { display: grid; gap: 10px; margin-top: 14px; }
  .trace .card h3 { font-size: 12.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--ink-2); margin: 0 0 8px; }
  .trace .card h3 span { color: var(--accent); }
  .trace .original { max-height: 220px; overflow: auto; }
  .kv { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 16px; margin: 0; font-size: 14px; }
  .kv dt { color: var(--ink-2); }
  .kv dd { margin: 0; overflow-wrap: anywhere; }
  .kv code { font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .rule-line { font-size: 15px; margin: 0; }
  .rule-line b { font-weight: 600; }
  .verdict { margin: 8px 0 0; font-size: 13.5px; color: var(--ink-2); }
  .go-inbox { margin-top: 10px; }

  .metric { display: flex; flex-direction: column-reverse; gap: 5px; min-width: 76px; }
  .bar { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; }
  .bar span { display: block; height: 100%; background: var(--accent); border-radius: 0 4px 4px 0; }
  .metric .val { font-variant-numeric: tabular-nums; white-space: nowrap; font-size: 13.5px; }
  tbody th { white-space: nowrap; }
  .metric .val small { color: var(--ink-2); font-size: 12.5px; }
  .ids { display: flex; flex-wrap: wrap; gap: 4px; }
  .id-link { font: 500 12.5px ui-monospace, SFMono-Regular, Menlo, monospace; border: 1px solid var(--line); background: var(--surface); border-radius: 4px; padding: 1px 6px; cursor: pointer; color: var(--accent); }
  .id-link:hover { background: var(--accent-soft); }
  .none { color: var(--ink-2); }
  .cm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
  .cm-grid figure { margin: 0; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 10px; }
  .cm-grid img { width: 100%; height: auto; display: block; }
  .cm-grid figcaption { font-size: 13px; color: var(--ink-2); margin-top: 6px; }
  .source-note { font-size: 12.5px; color: var(--ink-2); margin-top: 24px; }

  /* items that just moved to another group after changing the date */
  @keyframes moved { from { background: var(--mark); } to { background: transparent; } }
  .item.moved { animation: moved 1.6s ease-out; }

  @media (max-width: 760px) {
    .pipeline { grid-template-columns: 1fr; gap: 22px; }
    .pipeline li + li::before { content: "\2193"; left: 50%; top: -19px; transform: translateX(-50%); }
  }
  @media (max-width: 600px) {
    .wrap { padding: 18px 16px 56px; }
    .io { grid-template-columns: 1fr; }
    .tabs { width: 100%; }
    .tabs a { flex: 1; text-align: center; padding: 6px 4px; }
    th, td { padding: 8px; }
    .hello { margin-top: 32px; }
    .viewas { flex-wrap: wrap; }
    .date-note { text-align: left; }
    .stats li { padding: 12px; }
    .stats strong { font-size: 22px; }
    .group { margin-top: 36px; }
    .group + .fold { margin-top: 36px; }
    .fold + .fold { margin-top: 0; }
    .group-head .desc, .fold > summary .desc { display: none; }
    .fold > summary .chev { margin-left: auto; }
    .item-head { padding: 14px; gap: 2px 8px; }
    .countdown, .g-Urgent .countdown { font-size: 13px; padding-top: 3px; }
    .subject { font-size: 16px; }
    .g-Urgent .item-head { padding: 16px 14px 16px 18px; }
    .g-Urgent .subject { font-size: 17px; }
    .detail, .g-Urgent .detail { padding: 0 14px 16px 14px; }
    .fold .item-head { padding: 12px 14px; }
  }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; animation: none !important; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="project">
    <p class="kicker">GE2340 course project · Group 8</p>
    <p class="brand">AI-Powered Student Daily Prioritizer &amp; Noise Filter</p>
  </header>

  <div class="topbar">
    <nav class="tabs" aria-label="Views">
      <a href="#inbox" data-view="inbox">Inbox</a>
      <a href="#how" data-view="how">How it works</a>
      <a href="#eval" data-view="eval">Evaluation</a>
    </nav>
    <div class="viewas">
      <label for="viewDate">Viewing as</label>
      <input type="date" id="viewDate">
      <button type="button" class="chip-btn" id="todayBtn" aria-pressed="true">Today</button>
    </div>
    <p class="date-note" id="dateNote"></p>
  </div>

  <div id="view-inbox" class="view">
    <section class="hello" aria-labelledby="greeting">
      <h1 id="greeting">Hello.</h1>
      <p class="dateline" id="dateline"></p>
      <ul class="stats" id="stats" aria-live="polite"></ul>
    </section>
    <main id="groups"></main>
  </div>

  <div id="view-how" class="view" hidden>
    <section class="block">
      <h1 class="page-title">How it works</h1>
      <p class="lead">Students get dozens of announcements a week from Canvas, departments and the residence office.
      The few with real deadlines get buried among events and newsletters. The system reads every announcement,
      pulls out what matters and sorts the inbox by urgency.</p>
      <dl class="io">
        <div><dt>Input</dt><dd>One announcement per row: sender, date received, subject and full text.</dd></div>
        <div><dt>Output</dt><dd>A priority per announcement (Urgent, High, Medium, Low or Expired), the deadline, the task, a next step, and the sentence the decision is based on.</dd></div>
      </dl>
    </section>

    <section class="block">
      <h2>Pipeline</h2>
      <ol class="pipeline" id="pipeline"></ol>
    </section>

    <section class="block">
      <h2>Priority rule</h2>
      <p class="sub">Step 3 is a fixed rule, not the model. Rows: importance from the model. Columns: time left to the deadline.
      No deadline: priority = importance. Deadline passed: Expired.</p>
      <div class="table-wrap"><table class="matrix" id="matrix"></table></div>
    </section>

    <section class="block">
      <h2>Follow one announcement through the system</h2>
      <label class="pick-label" for="tracePick">Announcement</label>
      <select id="tracePick"></select>
      <div id="trace"></div>
    </section>

    <section class="block" id="profileBlock" hidden>
      <h2>Student profile used in this run</h2>
      <p class="sub">Appended to the prompt so the model can mark announcements that do not apply to this student. Contains no names, IDs or emails.</p>
      <dl class="kv" id="profile"></dl>
    </section>
  </div>

  <div id="view-eval" class="view" hidden>
    <section class="block">
      <h1 class="page-title">Evaluation</h1>
      <p class="lead" id="evalLead"></p>
    </section>
    <div id="evalBody"></div>
  </div>

</div>

<script id="config" type="application/json">__CONFIG__</script>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  "use strict";
  var CONFIG = JSON.parse(document.getElementById("config").textContent);
  var MESSAGES = JSON.parse(document.getElementById("data").textContent);
  var RULES = CONFIG.rules;
  var TZ = "Asia/Hong_Kong";
  var TZ_OFFSET_H = 8;               // Hong Kong is UTC+8 all year (no daylight saving)
  var HOUR = 3600 * 1000;

  var GROUPS = [
    { key: "Urgent",  title: "Needs your attention now", desc: "Important, and the deadline is close" },
    { key: "High",    title: "Due soon",                desc: "Important tasks with a deadline" },
    { key: "Medium",  title: "Worth reading",           desc: "Useful, but no rush" },
    { key: "Low",     title: "Filtered out",            desc: "Info, events, newsletters, reminders", fold: true },
    { key: "Expired", title: "Past deadline",           desc: "The deadline has already passed", fold: true }
  ];
  var KNOWN = { Urgent: 1, High: 1, Medium: 1, Low: 1, Expired: 1 };

  // ---------- dates (all deadlines are Hong Kong local time) ----------
  function parseHK(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec((text || "").trim());
    if (!m) return null;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - TZ_OFFSET_H, +m[5]);
  }
  function hkDayString(ms) {
    return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(ms));
  }
  function dayToRefMs(day) {          // "YYYY-MM-DD" -> that day at REFERENCE_HOUR, HK time
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], RULES.reference_hour - TZ_OFFSET_H, 0) : null;
  }
  var fmtDeadline = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  var fmtLong = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "long", day: "numeric", month: "long", year: "numeric" });
  var fmtHour = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "numeric", hour12: false });
  var rtf = new Intl.RelativeTimeFormat("en", { numeric: "always" });

  function relative(ms) {             // "in 5 hours", "in 2 days", "3 days ago"
    var h = ms / HOUR, a = Math.abs(h);
    if (a < 1) return rtf.format(Math.round(ms / 60000), "minute");
    if (a < 48) return rtf.format(Math.round(h), "hour");
    return rtf.format(Math.round(h / 24), "day");
  }
  // ---------- the rule: same as compute_priority() in prioritizer.py ----------
  function computePriority(importance, deadlineMs, refMs) {
    var row = RULES.matrix[importance];
    if (!row) return null;                         // unknown importance -> use stored value
    if (deadlineMs === null) return importance;
    var left = deadlineMs - refMs;
    if (left < 0) return "Expired";
    if (left <= RULES.short_window_hours * HOUR) return row[0];
    if (left <= RULES.medium_window_hours * HOUR) return row[1];
    return row[2];
  }

  // ---------- state ----------
  var state = { day: null, refMs: Date.now(), isToday: true };
  var expanded = {};
  var foldOpen = { Low: false, Expired: false };
  var lastGroup = {};

  MESSAGES.forEach(function (m) { m.deadlineMs = parseHK(m.deadline); });

  function priorityFor(m) {
    if (m.relevant === false) return "Low";       // profile says it does not apply to this student
    if (CONFIG.canRecompute) {
      var p = computePriority(m.importance, m.deadlineMs, state.refMs);
      if (p) return p;
    }
    return KNOWN[m.stored_priority] ? m.stored_priority : "Medium";   // unclassified -> keep visible
  }

  // ---------- DOM helpers ----------
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  var CHEV = '<svg class="chev" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  // Put the original text into `target`, with the evidence sentence wrapped in <mark>.
  function renderOriginal(target, body, evidence) {
    if (!body) { target.textContent = "Original text not available."; return true; }
    var ev = (evidence || "").trim().replace(/^["'“‘]+|["'”’]+$/g, "");
    if (!ev) { target.textContent = body; return true; }
    // The model sometimes shortens a quote with "..." - highlight each part in order.
    var parts = ev.split(/\s*(?:\.\.\.|…)\s*/).filter(function (x) { return x.trim().length >= 3; });
    var spans = [], from = 0;
    var ok = parts.every(function (part) {
      var match = null;
      [part, part.replace(/[.!?;,]+$/, "")].some(function (candidate) {
        if (candidate.length < 3) return false;
        var pattern = candidate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
        var re = new RegExp(pattern, "ig"); re.lastIndex = from;
        match = re.exec(body);
        return !!match;
      });
      if (!match) return false;
      spans.push([match.index, match.index + match[0].length]);
      from = match.index + match[0].length;
      return true;
    });
    if (!ok || !spans.length) { target.textContent = body; return false; }
    var pos = 0;
    spans.forEach(function (sp) {
      target.appendChild(document.createTextNode(body.slice(pos, sp[0])));
      target.appendChild(el("mark", null, body.slice(sp[0], sp[1])));
      pos = sp[1];
    });
    target.appendChild(document.createTextNode(body.slice(pos)));
    return true;
  }

  function renderItem(m, group) {
    var item = el("article", "item");
    item.dataset.id = m.id;
    var detailId = "detail-" + m.id;
    var head = el("button", "item-head");
    head.type = "button";
    head.setAttribute("aria-controls", detailId);
    head.setAttribute("aria-expanded", expanded[m.id] ? "true" : "false");

    var left = m.deadlineMs !== null ? m.deadlineMs - state.refMs : null;

    head.appendChild(el("span", "dot"));

    var main = el("span", "main");
    main.appendChild(el("span", "subject", m.subject));
    var meta = el("span", "meta");
    meta.appendChild(document.createTextNode((m.source || "Unknown source") + " · "));
    if (left === null) {
      meta.appendChild(document.createTextNode(m.deadline ? "Deadline: " + m.deadline : "No deadline"));
    } else {
      meta.appendChild(document.createTextNode((left < 0 ? "Was due " : "Due ") + fmtDeadline.format(new Date(m.deadlineMs))));
    }
    main.appendChild(meta);
    if (m.relevant === false) {
      var nr = el("span", "notrel");
      nr.appendChild(el("b", null, "Not relevant to you"));
      if (m.relevance_reason) nr.appendChild(document.createTextNode(" \u00b7 " + m.relevance_reason));
      main.appendChild(nr);
    }

    if (group !== "Low" && group !== "Expired" && (m.task || m.action)) {
      var lines = el("span", "lines");
      if (m.task) { var t = el("span"); t.appendChild(el("b", null, "To do: ")); t.appendChild(document.createTextNode(m.task)); lines.appendChild(t); }
      if (m.action) { var a = el("span"); a.appendChild(el("b", null, "Next step: ")); a.appendChild(document.createTextNode(m.action)); lines.appendChild(a); }
      main.appendChild(lines);
    }
    head.appendChild(main);
    var soon = left !== null && left >= 0 && left < RULES.short_window_hours * HOUR;
    head.appendChild(el("span", "countdown" + (soon ? " soon" : ""), left === null ? "No deadline" : relative(left)));
    head.insertAdjacentHTML("beforeend", CHEV);
    item.appendChild(head);

    // expanded detail: original text with the evidence highlighted + why
    var detail = el("div", "detail");
    detail.id = detailId;
    detail.hidden = !expanded[m.id];
    var label = el("p", "original-label", "Original message" + (m.received ? " · received " + m.received : "") + (m.evidence ? " · highlighted: the part the AI based its decision on" : ""));
    detail.appendChild(label);
    var orig = el("p", "original");
    var found = renderOriginal(orig, m.body, m.evidence);
    detail.appendChild(orig);
    if (!found) detail.appendChild(el("p", "evidence-miss", "AI quoted: “" + m.evidence + "” (not found word-for-word in the text)"));

    var why = el("ul", "why");
    function fact(k, v) { if (!v) return; var li = el("li"); li.appendChild(document.createTextNode(k + " ")); li.appendChild(el("b", null, v)); why.appendChild(li); }
    if ((group === "Low" || group === "Expired") && m.task) fact("To do:", m.task);
    if ((group === "Low" || group === "Expired") && m.action) fact("Next step:", m.action);
    fact("Importance (AI):", m.importance);
    if (CONFIG.canRecompute && RULES.matrix[m.importance]) {
      fact("Time left:", left === null ? "no deadline" : (left < 0 ? "passed" : Math.round(left / HOUR) + " h"));
      fact("Rule result:", group);
    }
    fact("LLM alone said:", m.llm_priority);
    if (m.relevant !== null && m.relevant !== undefined) fact("Relevant to you:", m.relevant ? "yes" : "no");
    detail.appendChild(why);
    item.appendChild(detail);

    head.addEventListener("click", function () {
      expanded[m.id] = !expanded[m.id];
      head.setAttribute("aria-expanded", expanded[m.id] ? "true" : "false");
      detail.hidden = !expanded[m.id];
      detail.classList.toggle("reveal", expanded[m.id]);
    });

    if (lastGroup[m.id] && lastGroup[m.id] !== group) item.classList.add("moved");
    return item;
  }

  function sortByDeadline(list, group) {
    return list.sort(function (a, b) {
      if (a.deadlineMs === null && b.deadlineMs === null) return 0;
      if (a.deadlineMs === null) return 1;
      if (b.deadlineMs === null) return -1;
      // past deadlines: most recently passed first; otherwise: soonest first
      return group === "Expired" ? b.deadlineMs - a.deadlineMs : a.deadlineMs - b.deadlineMs;
    });
  }

  function render() {
    var buckets = {};
    GROUPS.forEach(function (g) { buckets[g.key] = []; });
    var assigned = {};
    MESSAGES.forEach(function (m) {
      var p = priorityFor(m);
      assigned[m.id] = p;
      buckets[p].push(m);
    });

    // ---------- header ----------
    var hour = +fmtHour.format(new Date(state.refMs));
    document.getElementById("greeting").textContent =
      hour < 5 ? "Working late?" : hour < 12 ? "Good morning." : hour < 18 ? "Good afternoon." : "Good evening.";
    document.getElementById("dateline").textContent =
      fmtLong.format(new Date(state.refMs)) + (state.isToday ? "" : " (preview)") + " · " +
      MESSAGES.length + " message" + (MESSAGES.length === 1 ? "" : "s") + " in your inbox";

    var week = MESSAGES.filter(function (m) {
      if (m.deadlineMs === null || assigned[m.id] === "Expired") return false;
      var left = m.deadlineMs - state.refMs;
      return left >= 0 && left <= 7 * 24 * HOUR;
    }).length;
    var urgent = buckets.Urgent.length, noise = buckets.Low.length;
    var pct = MESSAGES.length ? Math.round(100 * noise / MESSAGES.length) : 0;
    var stats = document.getElementById("stats");
    stats.innerHTML = "";
    [
      ["s-urgent", urgent, "need attention now"],
      ["s-week", week, "due in the next 7 days"],
      ["s-noise", noise, "filtered out as noise", pct + "% of inbox"]
    ].forEach(function (s) {
      var li = el("li", s[0]);
      li.appendChild(el("strong", null, String(s[1])));
      li.appendChild(el("span", null, s[2]));
      if (s[3]) li.appendChild(el("span", "pct", s[3]));
      stats.appendChild(li);
    });

    // ---------- groups ----------
    var root = document.getElementById("groups");
    root.innerHTML = "";
    GROUPS.forEach(function (g) {
      var items = sortByDeadline(buckets[g.key], g.key);
      if (!items.length && g.key !== "Urgent") return;

      var section;
      var headingId = "h-" + g.key;
      if (g.fold) {
        section = el("details", "fold group g-" + g.key);
        section.open = !!foldOpen[g.key];
        section.addEventListener("toggle", function () { foldOpen[g.key] = section.open; });
        var sum = el("summary");
        sum.appendChild(el("h2", null, g.title));
        sum.appendChild(el("span", "count", "(" + items.length + ")"));
        sum.appendChild(el("span", "desc", g.desc));
        sum.insertAdjacentHTML("beforeend", CHEV);
        section.appendChild(sum);
      } else {
        section = el("section", "group g-" + g.key);
        section.setAttribute("aria-labelledby", headingId);
        var head = el("div", "group-head");
        var h2 = el("h2", null, g.title); h2.id = headingId;
        head.appendChild(h2);
        if (items.length) head.appendChild(el("span", "count", String(items.length)));
        head.appendChild(el("span", "desc", g.desc));
        section.appendChild(head);
      }

      if (!items.length) {
        var calm = el("div", "calm");
        calm.textContent = "Nothing urgent right now. You’re on top of things.";
        section.appendChild(calm);
      } else {
        var list = el("div", "list");
        items.forEach(function (m) { list.appendChild(renderItem(m, g.key)); });
        section.appendChild(list);
      }
      root.appendChild(section);
    });
    lastGroup = assigned;
  }


  // ---------- tabs (#inbox, #how, #eval) ----------
  var VIEWS = ["inbox", "how", "eval"];
  function showView(name) {
    if (VIEWS.indexOf(name) < 0) name = "inbox";
    VIEWS.forEach(function (v) {
      document.getElementById("view-" + v).hidden = v !== name;
    });
    document.querySelectorAll(".tabs a").forEach(function (a) {
      if (a.dataset.view === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }
  window.addEventListener("hashchange", function () { showView(location.hash.slice(1)); });

  function openInInbox(id) {
    expanded[id] = true;
    var m = MESSAGES.filter(function (x) { return x.id === id; })[0];
    if (m) { var g = priorityFor(m); if (foldOpen.hasOwnProperty(g)) foldOpen[g] = true; }
    render();
    location.hash = "#inbox";
    showView("inbox");
    var node = document.querySelector('.item[data-id="' + id + '"]');
    if (node) { node.scrollIntoView({ block: "center" }); node.classList.remove("moved"); void node.offsetWidth; node.classList.add("moved"); }
  }

  function pri(p) { return el("span", "pri p-" + p, p); }
  function hoursText(h) { return h < 48 ? h + " h" : (Math.round(h / 24 * 10) / 10) + " days"; }

  // ---------- How it works ----------
  function renderHow() {
    var model = RULES.model || "DeepSeek";
    var steps = [
      ["Announcement", "Sender, date received, subject and text, read from a CSV file."],
      ["Language model (" + model + ")", "Temperature 0, JSON output. Returns importance, deadline, task, next step, the evidence sentence" + (CONFIG.profile ? " and whether it applies to this student." : "."), true],
      ["Priority rule (Python)", "Combines importance with time left: ≤ " + hoursText(RULES.short_window_hours) + " escalates one level, ≤ " + hoursText(RULES.medium_window_hours) + " keeps it, later keeps it."],
      ["Prioritised inbox", "Grouped by priority, sorted by deadline, recalculated for any day in the browser."]
    ];
    var ol = document.getElementById("pipeline");
    ol.innerHTML = "";
    steps.forEach(function (st, i) {
      var li = el("li", st[2] ? "ai" : "");
      li.appendChild(el("span", "num", "Step " + (i + 1) + (st[2] ? " · AI" : "")));
      li.appendChild(el("h3", null, st[0]));
      li.appendChild(el("p", null, st[1]));
      ol.appendChild(li);
    });

    var t = document.getElementById("matrix");
    t.innerHTML = "";
    var thead = el("thead"), hr = el("tr");
    ["Importance \\ time left", "≤ " + hoursText(RULES.short_window_hours), "≤ " + hoursText(RULES.medium_window_hours), "> " + hoursText(RULES.medium_window_hours)].forEach(function (h) { hr.appendChild(el("th", null, h)); });
    thead.appendChild(hr); t.appendChild(thead);
    var tb = el("tbody");
    ["Low", "Medium", "High"].forEach(function (imp) {
      var tr = el("tr");
      tr.appendChild(el("th", null, imp));
      (RULES.matrix[imp] || []).forEach(function (p) { var td = el("td"); td.appendChild(pri(p)); tr.appendChild(td); });
      tb.appendChild(tr);
    });
    t.appendChild(tb);

    var sel = document.getElementById("tracePick");
    if (!sel.options.length) {
      MESSAGES.forEach(function (m) { var o = el("option", null, m.id + " · " + m.subject); o.value = m.id; sel.appendChild(o); });
      var first = MESSAGES.filter(function (m) { return m.evidence && m.deadlineMs !== null && m.importance === "High"; })[0] || MESSAGES[0];
      if (first) sel.value = first.id;
      sel.addEventListener("change", renderTrace);
    }
    renderTrace();

    if (CONFIG.profile) {
      document.getElementById("profileBlock").hidden = false;
      var dl = document.getElementById("profile");
      dl.innerHTML = "";
      Object.keys(CONFIG.profile).forEach(function (k) {
        var v = CONFIG.profile[k];
        dl.appendChild(el("dt", null, k.replace(/_/g, " ")));
        dl.appendChild(el("dd", null, Array.isArray(v) ? v.join(", ") : String(v)));
      });
    }
  }

  function renderTrace() {
    var id = document.getElementById("tracePick").value;
    var m = MESSAGES.filter(function (x) { return x.id === id; })[0];
    var box = document.getElementById("trace");
    box.innerHTML = "";
    if (!m) return;
    var wrap = el("div", "trace");

    var c1 = el("div", "card");
    var h1 = el("h3"); h1.appendChild(el("span", null, "1 ")); h1.appendChild(document.createTextNode("Input")); c1.appendChild(h1);
    c1.appendChild(el("p", "meta", (m.source || "Unknown source") + (m.received ? " · received " + m.received : "")));
    var orig = el("p", "original"); orig.style.marginTop = "8px";
    var hit = renderOriginal(orig, m.body, m.evidence);
    c1.appendChild(orig);
    if (!hit) c1.appendChild(el("p", "evidence-miss", "The model's evidence quote was not found word-for-word in the text."));
    wrap.appendChild(c1);

    var c2 = el("div", "card");
    var h2 = el("h3"); h2.appendChild(el("span", null, "2 ")); h2.appendChild(document.createTextNode("What the model returned (JSON)")); c2.appendChild(h2);
    var kv = el("dl", "kv");
    function row(k, v) { if (v === "" || v === null || v === undefined) return; kv.appendChild(el("dt", null, k)); var dd = el("dd"); dd.appendChild(el("code", null, String(v))); kv.appendChild(dd); }
    row("importance", m.importance);
    row("deadline", m.deadline || "null");
    row("task", m.task);
    row("suggested_action", m.action);
    row("evidence", m.evidence);
    if (m.relevant !== null && m.relevant !== undefined) { row("relevant_to_user", m.relevant); row("relevance_reason", m.relevance_reason); }
    row("llm_priority", m.llm_priority);
    c2.appendChild(kv);
    c2.appendChild(el("p", "verdict", "The highlighted sentence in step 1 is the evidence the model quoted. llm_priority is stored only for comparison."));
    wrap.appendChild(c2);

    var c3 = el("div", "card");
    var h3 = el("h3"); h3.appendChild(el("span", null, "3 ")); h3.appendChild(document.createTextNode("Priority rule")); c3.appendChild(h3);
    var line = el("p", "rule-line");
    var final = priorityFor(m);
    var day = state.isToday ? "now" : state.day + " " + String(RULES.reference_hour).padStart(2, "0") + ":00";
    if (m.relevant === false) {
      line.appendChild(document.createTextNode("Marked as not relevant to this student → "));
    } else if (m.deadlineMs === null) {
      line.appendChild(document.createTextNode("Importance "));
      line.appendChild(el("b", null, m.importance || "?"));
      line.appendChild(document.createTextNode(", no deadline → "));
    } else {
      var left = m.deadlineMs - state.refMs;
      line.appendChild(document.createTextNode("Importance "));
      line.appendChild(el("b", null, m.importance || "?"));
      line.appendChild(document.createTextNode(" × " + (left < 0 ? "deadline passed" : Math.round(left / HOUR) + " h left") + " (as of " + day + ") → "));
    }
    line.appendChild(pri(final));
    c3.appendChild(line);
    var same = (m.llm_priority === final);
    c3.appendChild(el("p", "verdict", "LLM alone said " + (m.llm_priority || "nothing") + (same ? " (same result)." : ". The rule decides the final priority.") + " Change the “Viewing as” date to see the rule react."));
    var b = el("button", "chip-btn go-inbox", "Show in inbox"); b.type = "button";
    b.addEventListener("click", function () { openInInbox(m.id); });
    c3.appendChild(b);
    wrap.appendChild(c3);
    box.appendChild(wrap);
  }

  // ---------- Evaluation ----------
  function frac(a, b) { a = +a; b = +b; return { a: a, b: b, pct: b ? Math.round(100 * a / b) : 0 }; }
  function metricCell(a, b) {
    var f = frac(a, b), td = el("td"), wrap = el("div", "metric");
    var bar = el("div", "bar"); var fill = el("span"); fill.style.width = f.pct + "%"; bar.appendChild(fill);
    bar.title = f.a + " of " + f.b;
    var val = el("span", "val", f.pct + "% "); val.appendChild(el("small", null, f.a + "/" + f.b));
    wrap.appendChild(bar); wrap.appendChild(val); td.appendChild(wrap);
    return td;
  }
  function table(headers, rows) {
    var wrapDiv = el("div", "table-wrap"), t = el("table"), th = el("thead"), tr = el("tr");
    headers.forEach(function (h) { tr.appendChild(el("th", null, h)); });
    th.appendChild(tr); t.appendChild(th);
    var tb = el("tbody"); rows.forEach(function (r) { tb.appendChild(r); }); t.appendChild(tb);
    wrapDiv.appendChild(t); return wrapDiv;
  }
  function section(title, sub, content) {
    var s = el("section", "block"); s.appendChild(el("h2", null, title));
    if (sub) s.appendChild(el("p", "sub", sub));
    s.appendChild(content); return s;
  }
  function idList(text) {
    var d = el("div", "ids"), ids = (text || "").split(/\s+/).filter(Boolean);
    if (!ids.length) { d.appendChild(el("span", "none", "none")); return d; }
    ids.forEach(function (id) {
      var b = el("button", "id-link", id); b.type = "button";
      var known = MESSAGES.some(function (m) { return m.id === id; });
      if (known) { b.title = "Open " + id + " in the inbox"; b.addEventListener("click", function () { openInInbox(id); }); }
      else b.disabled = true;
      d.appendChild(b);
    });
    return d;
  }

  function renderEval() {
    var lead = document.getElementById("evalLead"), body = document.getElementById("evalBody");
    body.innerHTML = "";
    var E = CONFIG.eval;
    if (!E || !E.runs.length) {
      lead.textContent = "No evaluation found. Run evaluate.py; it writes eval/summary.csv next to the results file, then rebuild this dashboard.";
      return;
    }
    var runs = E.runs.filter(function (r) { return r.all; });
    var a0 = runs[0].all, real = runs[0].real, syn = runs[0].synthetic;
    lead.textContent = a0.n + " announcements (" + (real ? real.n : "?") + " real, " + (syn ? syn.n : "?") +
      " synthetic) labelled by hand and compared with the system's output in " + runs.length + " runs." +
      (a0.urgent_counted_as_high === "yes" ? " The answer key has no Urgent level, so Urgent counts as High." : "");

    body.appendChild(section("Main results",
      "Priority correct: final priority equals the human label. High recall: share of truly important announcements the system flagged High. Noise filtered: announcements labelled Low that the system also put in Low.",
      table(["Run", "Priority correct", "High recall", "High precision", "Noise filtered"], runs.map(function (r) {
        var m = r.all, tr = el("tr");
        tr.appendChild(el("th", null, r.name));
        tr.appendChild(metricCell(m.final_correct, m.n));
        tr.appendChild(metricCell(m.high_found, m.high_in_key));
        tr.appendChild(metricCell(m.high_flagged_correct, m.high_flagged));
        tr.appendChild(metricCell(m.low_kept_low, m.low_in_key));
        return tr;
      }))));

    body.appendChild(section("Hybrid rule vs. LLM alone",
      "Same runs. Strict: Urgent is not counted as High.",
      table(["Run", "Hybrid", "LLM alone", "Hybrid (strict)", "LLM alone (strict)"], runs.map(function (r) {
        var m = r.all, tr = el("tr");
        tr.appendChild(el("th", null, r.name));
        tr.appendChild(metricCell(m.final_correct, m.n));
        tr.appendChild(metricCell(m.llm_correct, m.n));
        tr.appendChild(metricCell(m.final_correct_strict, m.n));
        tr.appendChild(metricCell(m.llm_correct_strict, m.n));
        return tr;
      }))));

    body.appendChild(section("Where it went wrong",
      "Click an ID to open that announcement in the inbox.",
      table(["Run", "Errors (too high / too low)", "Missed High", "False alarms"], runs.map(function (r) {
        var m = r.all, tr = el("tr");
        tr.appendChild(el("th", null, r.name));
        var errs = (+m.errors_over) + (+m.errors_under) + (+m.errors_other);
        tr.appendChild(el("td", "num-cell", errs + " (" + m.errors_over + " / " + m.errors_under + ")"));
        var t1 = el("td"); t1.appendChild(idList(m.high_missed_ids)); tr.appendChild(t1);
        var t2 = el("td"); t2.appendChild(idList(m.false_alarm_ids)); tr.appendChild(t2);
        return tr;
      }))));

    body.appendChild(section("Real vs. synthetic announcements", null,
      table(["Run", "Real", "Synthetic", "Deadline exact"], runs.map(function (r) {
        var tr = el("tr");
        tr.appendChild(el("th", null, r.name));
        tr.appendChild(r.real ? metricCell(r.real.final_correct, r.real.n) : el("td", null, "-"));
        tr.appendChild(r.synthetic ? metricCell(r.synthetic.final_correct, r.synthetic.n) : el("td", null, "-"));
        var withKey = r.all.n - r.all.deadline_both_empty - r.all.deadline_extra;
        tr.appendChild(metricCell(r.all.deadline_exact, withKey));
        return tr;
      }))));

    body.appendChild(section("Cost and speed", null,
      table(["Run", "Tokens in / out", "Cost (USD)", "Seconds per announcement"], runs.map(function (r) {
        var m = r.all, tr = el("tr");
        tr.appendChild(el("th", null, r.name));
        tr.appendChild(el("td", "num-cell", m.input_tokens + " / " + m.output_tokens));
        tr.appendChild(el("td", "num-cell", "$" + (+m.cost_usd).toFixed(4)));
        tr.appendChild(el("td", "num-cell", (+m.avg_seconds).toFixed(2)));
        return tr;
      }))));

    var imgs = runs.filter(function (r) { return r.confusion; });
    if (imgs.length) {
      var grid = el("div", "cm-grid");
      imgs.forEach(function (r) {
        var f = el("figure"), img = el("img"); img.src = r.confusion; img.alt = "Confusion matrix, " + r.name;
        f.appendChild(img); f.appendChild(el("figcaption", null, r.name)); grid.appendChild(f);
      });
      body.appendChild(section("Confusion matrices", "System priority vs. human label.", grid));
    }
    body.appendChild(el("p", "source-note", "Numbers from eval/summary.csv (evaluate.py). This inbox shows " + CONFIG.resultsFile + "."));
  }

  // ---------- date picker ----------
  var input = document.getElementById("viewDate");
  var todayBtn = document.getElementById("todayBtn");
  var note = document.getElementById("dateNote");

  function setDay(day) {
    var today = hkDayString(Date.now());
    if (!day || day === today) {
      state.isToday = true; state.refMs = Date.now(); state.day = today;
    } else {
      var ms = dayToRefMs(day);
      if (ms === null) return;
      state.isToday = false; state.refMs = ms; state.day = day;
    }
    input.value = state.day;
    todayBtn.setAttribute("aria-pressed", state.isToday ? "true" : "false");
    note.textContent = state.isToday ? "" :
      "Preview: priorities recalculated as of " + day + ", " + String(RULES.reference_hour).padStart(2, "0") + ":00 Hong Kong time.";
    render();
    renderTrace();
  }

  if (CONFIG.canRecompute) {
    input.addEventListener("change", function () { setDay(input.value); });
    todayBtn.addEventListener("click", function () { setDay(null); });
    var params = new URLSearchParams(location.search);
    if (params.get("open")) expanded[params.get("open")] = true;
    setDay(params.get("date"));
  } else {
    input.value = hkDayString(Date.now());
    input.disabled = true;
    todayBtn.disabled = true;
    note.textContent = "Date preview is off: this results.csv is from the older prioritizer (no ai_importance / ai_deadline). Showing the saved priorities.";
    var p2 = new URLSearchParams(location.search);
    if (p2.get("open")) expanded[p2.get("open")] = true;
    render();
  }
  renderHow();
  renderEval();
  showView(location.hash.slice(1));

})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
