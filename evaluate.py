"""
Evaluate prioritizer runs against the answer key (fasit.csv). No API calls.
GE2340 Course Project - AI-Powered Student Daily Prioritizer & Noise Filter

Usage:
    python evaluate.py --fasit fasit.csv \
        --run "Run 1: no profile=results/results_generic.csv" \
        --run "Run 2: profile v1=results/results_personal.csv" \
        --run "Run 3: profile v2=results/results_personal_v2.csv"

    Add more runs with more --run "name=file" arguments (order matters for changes.csv).
    --no-collapse-urgent   treat Urgent as different from High in the main numbers
                           (strict numbers are always reported as well)

Output (overwritten each time) in results/eval/:
    summary.csv, summary.md, summary_table.tex, confusion_<run>.png, errors.csv, changes.csv

Only the standard library + matplotlib (for the figures).
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
DEFAULT_FASIT = "fasit.csv"
DEFAULT_OUT_DIR = os.path.join("results", "eval")
DEFAULT_RUNS = [
    "Run 1: no profile=results/results_generic.csv",
    "Run 2: profile v1=results/results_personal.csv",
    "Run 3: profile v2=results/results_personal_v2.csv",
]
PRICE_INPUT_PER_M = 0.30      # USD per 1M input tokens (deepseek-flash, peak)
PRICE_OUTPUT_PER_M = 1.20     # USD per 1M output tokens

LEVELS = ["Low", "Medium", "High", "Urgent"]
RANK = {level: i for i, level in enumerate(LEVELS)}
CONFUSION_LABELS = ["Low", "Medium", "High"]
SUBSETS = ["all", "real", "synthetic"]


# ---------------------------------------------------------------------------
# Small helpers (pure functions, tested in test_evaluate.py)
# ---------------------------------------------------------------------------
def norm_id(value):
    return (value or "").strip()


def normalize_priority(value, collapse_urgent=True):
    """'high ' -> 'High'; Urgent -> High when collapsing. Unknown values are kept as-is."""
    value = (value or "").strip()
    for level in LEVELS + ["Expired"]:
        if value.lower() == level.lower():
            value = level
            break
    if collapse_urgent and value == "Urgent":
        return "High"
    return value


def is_high(value):
    """High including Urgent (used for recall / precision)."""
    return normalize_priority(value, collapse_urgent=True) == "High"


def direction(ai, truth):
    """'over' if the AI ranked higher than the answer key, 'under' if lower, else 'other'."""
    if ai in RANK and truth in RANK:
        if RANK[ai] > RANK[truth]:
            return "over"
        if RANK[ai] < RANK[truth]:
            return "under"
    return "other"     # e.g. Expired, INVALID(...), ERROR


def compare_deadline(ai, truth):
    """Classify one deadline pair.

    Returns one of: 'both_empty', 'exact', 'same_date' (same day, different time),
    'wrong_date', 'missed' (key has one, AI has none), 'extra' (AI has one, key has none).
    """
    ai, truth = (ai or "").strip(), (truth or "").strip()
    if not ai and not truth:
        return "both_empty"
    if truth and not ai:
        return "missed"
    if ai and not truth:
        return "extra"
    if ai == truth:
        return "exact"
    if ai[:10] == truth[:10]:
        return "same_date"
    return "wrong_date"


def cohen_kappa(a, b):
    """Cohen's kappa for two equally long label lists."""
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def parse_relevant(value):
    value = (value or "").strip().lower()
    return {"true": "true", "false": "false"}.get(value, value)


def load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "run"


def frac(num, den):
    return f"{num}/{den}" + (f" ({100 * num / den:.0f}%)" if den else "")


# ---------------------------------------------------------------------------
# Joining the answer key with one run
# ---------------------------------------------------------------------------
def join(fasit_rows, result_rows):
    """Return (pairs, skipped). pairs = list of (fasit_row, result_row).

    Only rows with include_in_eval = yes AND an id present in the results are used.
    skipped = list of (id, reason).
    """
    results = {norm_id(r.get("id")): r for r in result_rows}
    pairs, skipped = [], []
    fasit_ids = set()
    for f in fasit_rows:
        fid = norm_id(f.get("id"))
        fasit_ids.add(fid)
        if f.get("include_in_eval", "").strip().lower() != "yes":
            skipped.append((fid, f"include_in_eval = {f.get('include_in_eval') or 'empty'}"))
        elif fid not in results:
            skipped.append((fid, "not in results file"))
        else:
            pairs.append((f, results[fid]))
    for rid in results:
        if rid not in fasit_ids:
            skipped.append((rid, "in results file but not in fasit"))
    return pairs, skipped


# ---------------------------------------------------------------------------
# Metrics for one run (one subset of mails)
# ---------------------------------------------------------------------------
def metrics(pairs, collapse_urgent=True):
    n = len(pairs)
    m = {"n": n}

    def pri(row, col, collapse=collapse_urgent):
        return normalize_priority(row.get(col), collapse)

    truth = [pri(f, "label_priority_final") for f, _ in pairs]
    final = [pri(r, "final_priority") for _, r in pairs]
    llm = [pri(r, "ai_llm_priority") for _, r in pairs]
    ids = [norm_id(f.get("id")) for f, _ in pairs]

    # 1-2. accuracy (main = collapse setting, plus always strict)
    m["final_correct"] = sum(a == t for a, t in zip(final, truth))
    m["llm_correct"] = sum(a == t for a, t in zip(llm, truth))
    m["final_correct_strict"] = sum(pri(r, "final_priority", False) == pri(f, "label_priority_final", False) for f, r in pairs)
    m["llm_correct_strict"] = sum(pri(r, "ai_llm_priority", False) == pri(f, "label_priority_final", False) for f, r in pairs)
    m["importance_correct"] = sum(pri(r, "ai_importance") == pri(f, "label_importance") for f, r in pairs)

    # 3. High recall / precision (High includes Urgent)
    truth_high = [i for i, (f, _) in enumerate(pairs) if is_high(f.get("label_priority_final"))]
    ai_high = [i for i, (_, r) in enumerate(pairs) if is_high(r.get("final_priority"))]
    m["high_in_key"] = len(truth_high)
    m["high_found"] = sum(1 for i in truth_high if i in ai_high)
    m["high_flagged"] = len(ai_high)
    m["high_flagged_correct"] = sum(1 for i in ai_high if i in truth_high)
    m["high_missed_ids"] = [ids[i] for i in truth_high if i not in ai_high]
    m["false_alarm_ids"] = [ids[i] for i in ai_high if i not in truth_high]

    # 4. noise filter
    low_idx = [i for i, t in enumerate(truth) if t == "Low"]
    m["low_in_key"] = len(low_idx)
    m["low_kept_low"] = sum(1 for i in low_idx if final[i] == "Low")

    # 5. over- vs under-prioritisation among errors
    dirs = Counter(direction(a, t) for a, t in zip(final, truth) if a != t)
    m["over"], m["under"], m["other_errors"] = dirs["over"], dirs["under"], dirs["other"]

    # 6. deadlines
    dl = Counter(compare_deadline(r.get("ai_deadline"), f.get("label_deadline")) for f, r in pairs)
    for key in ("exact", "same_date", "wrong_date", "both_empty", "missed", "extra"):
        m["deadline_" + key] = dl[key]

    # 7. cost and time
    def num(row, col):
        try:
            return float(row.get(col) or 0)
        except ValueError:
            return 0.0
    m["input_tokens"] = int(sum(num(r, "input_tokens") for _, r in pairs))
    m["output_tokens"] = int(sum(num(r, "output_tokens") for _, r in pairs))
    m["cost_usd"] = m["input_tokens"] / 1e6 * PRICE_INPUT_PER_M + m["output_tokens"] / 1e6 * PRICE_OUTPUT_PER_M
    m["avg_seconds"] = sum(num(r, "seconds") for _, r in pairs) / n if n else 0.0
    return m


def evaluate_run(fasit_rows, result_rows, collapse_urgent=True):
    """Metrics for all mails and per origin. Returns (by_subset, pairs, skipped)."""
    pairs, skipped = join(fasit_rows, result_rows)
    by_subset = {}
    for subset in SUBSETS:
        chosen = pairs if subset == "all" else [p for p in pairs if p[0].get("origin", "").lower() == subset]
        by_subset[subset] = metrics(chosen, collapse_urgent)
    return by_subset, pairs, skipped


def confusion(pairs, collapse_urgent=True):
    """Rows = answer key, columns = AI (Low, Medium, High [, Other])."""
    counts = Counter()
    for f, r in pairs:
        t = normalize_priority(f.get("label_priority_final"), True)
        a = normalize_priority(r.get("final_priority"), True)
        counts[(t, a if a in CONFUSION_LABELS else "Other")] += 1
    cols = CONFUSION_LABELS + (["Other"] if any(c == "Other" for _, c in counts) else [])
    return [[counts[(t, a)] for a in cols] for t in CONFUSION_LABELS], cols


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------
def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summary_rows(runs, collapse_urgent):
    rows = []
    for name, _, by_subset, _, _ in runs:
        for subset in SUBSETS:
            m = by_subset[subset]
            if not m["n"]:
                continue
            rows.append({
                "run": name, "subset": subset, "n": m["n"],
                "urgent_counted_as_high": "yes" if collapse_urgent else "no",
                "final_correct": m["final_correct"], "llm_correct": m["llm_correct"],
                "final_correct_strict": m["final_correct_strict"], "llm_correct_strict": m["llm_correct_strict"],
                "importance_correct": m["importance_correct"],
                "high_found": m["high_found"], "high_in_key": m["high_in_key"],
                "high_flagged_correct": m["high_flagged_correct"], "high_flagged": m["high_flagged"],
                "high_missed_ids": " ".join(m["high_missed_ids"]), "false_alarm_ids": " ".join(m["false_alarm_ids"]),
                "low_kept_low": m["low_kept_low"], "low_in_key": m["low_in_key"],
                "errors_over": m["over"], "errors_under": m["under"], "errors_other": m["other_errors"],
                "deadline_exact": m["deadline_exact"], "deadline_same_date": m["deadline_same_date"],
                "deadline_wrong_date": m["deadline_wrong_date"], "deadline_both_empty": m["deadline_both_empty"],
                "deadline_missed": m["deadline_missed"], "deadline_extra": m["deadline_extra"],
                "input_tokens": m["input_tokens"], "output_tokens": m["output_tokens"],
                "cost_usd": round(m["cost_usd"], 5), "avg_seconds": round(m["avg_seconds"], 2),
            })
    return rows


def write_markdown(path, runs, kappa_info, collapse_urgent):
    L = []
    L.append("# Evaluation against the answer key\n")
    L.append(f"Urgent counted as High in the main numbers: **{'yes' if collapse_urgent else 'no'}**. "
             "Expired counts as wrong unless the key also says Expired.\n")

    L.append("## Main results (all mails)\n")
    L.append("| Run | n | Priority correct (hybrid) | LLM alone | Importance correct | High recall | High precision | Noise filtered (key Low → AI Low) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for name, _, s, _, _ in runs:
        m = s["all"]
        L.append(f"| {name} | {m['n']} | {frac(m['final_correct'], m['n'])} | {frac(m['llm_correct'], m['n'])} | "
                 f"{frac(m['importance_correct'], m['n'])} | {frac(m['high_found'], m['high_in_key'])} | "
                 f"{frac(m['high_flagged_correct'], m['high_flagged'])} | {frac(m['low_kept_low'], m['low_in_key'])} |")

    L.append("\n## Real vs. synthetic mails (priority correct, hybrid)\n")
    L.append("| Run | Real | Synthetic |")
    L.append("|---|---|---|")
    for name, _, s, _, _ in runs:
        L.append(f"| {name} | {frac(s['real']['final_correct'], s['real']['n'])} | "
                 f"{frac(s['synthetic']['final_correct'], s['synthetic']['n'])} |")

    L.append("\n## Strict comparison (Urgent ≠ High)\n")
    L.append("| Run | Priority correct (hybrid) | LLM alone |")
    L.append("|---|---|---|")
    for name, _, s, _, _ in runs:
        m = s["all"]
        L.append(f"| {name} | {frac(m['final_correct_strict'], m['n'])} | {frac(m['llm_correct_strict'], m['n'])} |")

    L.append("\n## Errors: over- vs. under-prioritised\n")
    L.append("| Run | Errors | AI too high | AI too low | Other (Expired/invalid) |")
    L.append("|---|---|---|---|---|")
    for name, _, s, _, _ in runs:
        m = s["all"]
        L.append(f"| {name} | {m['n'] - m['final_correct']} | {m['over']} | {m['under']} | {m['other_errors']} |")

    L.append("\n## Missed High and false alarms\n")
    for name, _, s, _, _ in runs:
        m = s["all"]
        L.append(f"- **{name}**: missed High: {', '.join(m['high_missed_ids']) or '–'}; "
                 f"false alarms: {', '.join(m['false_alarm_ids']) or '–'}")

    L.append("\n## Deadlines\n")
    L.append("| Run | Exact | Same date, other time | Wrong date | Both empty | Missed | Extra |")
    L.append("|---|---|---|---|---|---|---|")
    for name, _, s, _, _ in runs:
        m = s["all"]
        L.append(f"| {name} | {m['deadline_exact']} | {m['deadline_same_date']} | {m['deadline_wrong_date']} | "
                 f"{m['deadline_both_empty']} | {m['deadline_missed']} | {m['deadline_extra']} |")
    L.append("\n'Same date' here means same day but a different time; same day in total = exact + same date.")

    L.append("\n## Cost and time\n")
    L.append("| Run | Input tokens | Output tokens | Cost (USD) | Avg. seconds per mail |")
    L.append("|---|---|---|---|---|")
    for name, _, s, _, _ in runs:
        m = s["all"]
        L.append(f"| {name} | {m['input_tokens']} | {m['output_tokens']} | {m['cost_usd']:.4f} | {m['avg_seconds']:.2f} |")

    L.append("\n## Answer key: AI-assisted label vs. final label\n")
    n, agree, kappa = kappa_info
    L.append(f"label_priority_AI vs. label_priority_final on {n} mails: agreement {frac(agree, n)}, "
             f"Cohen's kappa = {kappa:.2f}." if kappa is not None else "No rows to compare.")
    L.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def tex_escape(text):
    return re.sub(r"([&%$#_{}])", r"\\\1", text)


def write_latex(path, runs, collapse_urgent):
    def cell(num, den):
        return f"{num}/{den} ({100 * num / den:.0f}\\%)" if den else "--"
    L = [
        "% Requires \\usepackage{booktabs}",
        "\\begin{table}[ht]",
        "\\centering",
        "\\small",
        "\\caption{Prioritizer runs compared with the answer key"
        + (" (Urgent counted as High)" if collapse_urgent else "") + ".}",
        "\\label{tab:eval-summary}",
        "\\begin{tabular}{lrrrrr}",
        "\\toprule",
        "Run & Hybrid correct & LLM alone & High recall & High precision & Noise filtered \\\\",
        "\\midrule",
    ]
    for name, _, s, _, _ in runs:
        m = s["all"]
        L.append(f"{tex_escape(name)} & {cell(m['final_correct'], m['n'])} & {cell(m['llm_correct'], m['n'])} & "
                 f"{cell(m['high_found'], m['high_in_key'])} & {cell(m['high_flagged_correct'], m['high_flagged'])} & "
                 f"{cell(m['low_kept_low'], m['low_in_key'])} \\\\")
    L += ["\\bottomrule", "\\end{tabular}", "\\end{table}", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def plot_confusion(path, matrix, cols, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("calm", ["#FFFFFF", "#CFE2E0", "#2F6F73"])
    fig, ax = plt.subplots(figsize=(3.2 + 0.6 * (len(cols) - 3), 2.9), dpi=200)
    vmax = max(max(row) for row in matrix) or 1
    ax.imshow(matrix, cmap=cmap, vmin=0, vmax=vmax)
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            ax.text(j, i, str(value), ha="center", va="center", fontsize=11,
                    fontweight="bold" if i == j else "normal",
                    color="white" if value > 0.6 * vmax else "#2A2D33")
    ax.set_xticks(range(len(cols)), cols, fontsize=9)
    ax.set_yticks(range(len(CONFUSION_LABELS)), CONFUSION_LABELS, fontsize=9)
    ax.set_xlabel("AI (final priority)", fontsize=9)
    ax.set_ylabel("Answer key", fontsize=9)
    ax.set_title(title, fontsize=9.5, pad=8)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([x - 0.5 for x in range(1, len(cols))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(CONFUSION_LABELS))], minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def error_rows(name, pairs, collapse_urgent):
    rows = []
    for f, r in pairs:
        truth = normalize_priority(f.get("label_priority_final"), collapse_urgent)
        ai = normalize_priority(r.get("final_priority"), collapse_urgent)
        if ai == truth:
            continue
        rows.append({
            "id": norm_id(f.get("id")), "origin": f.get("origin", ""), "run": name,
            "ai_priority": r.get("final_priority", ""), "key_priority": f.get("label_priority_final", ""),
            "ai_importance": r.get("ai_importance", ""),
            "ai_relevant_to_user": parse_relevant(r.get("ai_relevant_to_user")),
            "ai_deadline": r.get("ai_deadline", ""), "key_deadline": f.get("label_deadline", ""),
            "direction": direction(ai, truth),
        })
    return rows


def change_rows(runs, collapse_urgent):
    rows = []
    for (name_a, _, _, pairs_a, _), (name_b, _, _, pairs_b, _) in zip(runs, runs[1:]):
        b = {norm_id(f.get("id")): r for f, r in pairs_b}
        for f, ra in pairs_a:
            fid = norm_id(f.get("id"))
            if fid not in b:
                continue
            truth = normalize_priority(f.get("label_priority_final"), collapse_urgent)
            pa = normalize_priority(ra.get("final_priority"), collapse_urgent)
            pb = normalize_priority(b[fid].get("final_priority"), collapse_urgent)
            if pa == pb:
                continue
            change = "better" if pb == truth else "worse" if pa == truth else "still wrong"
            rows.append({"id": fid, "origin": f.get("origin", ""), "from_run": name_a, "to_run": name_b,
                         "from_priority": pa, "to_priority": pb, "key_priority": truth, "change": change})
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_run(value):
    name, sep, path = value.partition("=")
    if not sep or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError('use --run "Name=path/to/results.csv"')
    return name.strip(), path.strip()


def main():
    parser = argparse.ArgumentParser(description="Compare prioritizer results with the answer key.")
    parser.add_argument("--fasit", default=DEFAULT_FASIT, help=f"answer key CSV (default: {DEFAULT_FASIT})")
    parser.add_argument("--run", action="append", type=parse_run,
                        help='"Name=results.csv"; repeat for more runs (default: the three standard runs)')
    parser.add_argument("--collapse-urgent", action=argparse.BooleanOptionalAction, default=True,
                        help="count Urgent as High in the main numbers (default: on)")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"output folder (default: {DEFAULT_OUT_DIR})")
    args = parser.parse_args()
    run_specs = args.run or [parse_run(r) for r in DEFAULT_RUNS]
    collapse = args.collapse_urgent

    fasit = load_csv(args.fasit)
    os.makedirs(args.out_dir, exist_ok=True)

    runs = []
    for name, path in run_specs:
        if not os.path.exists(path):
            sys.exit(f"Error: results file for '{name}' not found: {path}")
        by_subset, pairs, skipped = evaluate_run(fasit, load_csv(path), collapse)
        runs.append((name, path, by_subset, pairs, skipped))

    # skipped ids
    print(f"Answer key: {args.fasit} ({len(fasit)} rows). Urgent counted as High: {'yes' if collapse else 'no'}\n")
    for name, path, _, pairs, skipped in runs:
        print(f"{name}  [{path}]  evaluated: {len(pairs)}")
        for sid, reason in skipped:
            print(f"   skipped {sid}: {reason}")

    # 8. agreement inside the answer key
    included = [f for f in fasit if f.get("include_in_eval", "").lower() == "yes"]
    a = [normalize_priority(f.get("label_priority_AI"), collapse) for f in included]
    b = [normalize_priority(f.get("label_priority_final"), collapse) for f in included]
    kappa_info = (len(included), sum(x == y for x, y in zip(a, b)), cohen_kappa(a, b))

    # files
    rows = summary_rows(runs, collapse)
    write_csv(os.path.join(args.out_dir, "summary.csv"), rows, list(rows[0].keys()))
    write_markdown(os.path.join(args.out_dir, "summary.md"), runs, kappa_info, collapse)
    write_latex(os.path.join(args.out_dir, "summary_table.tex"), runs, collapse)

    errors = [row for name, _, _, pairs, _ in runs for row in error_rows(name, pairs, collapse)]
    write_csv(os.path.join(args.out_dir, "errors.csv"), errors,
              ["id", "origin", "run", "ai_priority", "key_priority", "ai_importance", "ai_relevant_to_user",
               "ai_deadline", "key_deadline", "direction"])
    changes = change_rows(runs, collapse)
    write_csv(os.path.join(args.out_dir, "changes.csv"), changes,
              ["id", "origin", "from_run", "to_run", "from_priority", "to_priority", "key_priority", "change"])

    for name, _, _, pairs, _ in runs:
        matrix, cols = confusion(pairs, collapse)
        plot_confusion(os.path.join(args.out_dir, f"confusion_{slug(name)}.png"), matrix, cols, name)

    # terminal summary
    print("\nRun                         Hybrid        LLM alone     High recall   Noise filtered")
    for name, _, s, _, _ in runs:
        m = s["all"]
        print(f"{name[:27]:<27} {m['final_correct']:>2}/{m['n']:<10} {m['llm_correct']:>2}/{m['n']:<10} "
              f"{m['high_found']:>2}/{m['high_in_key']:<10} {m['low_kept_low']:>2}/{m['low_in_key']}")
    n, agree, kappa = kappa_info
    if kappa is not None:
        print(f"\nAnswer key: label_priority_AI vs. final agree on {agree}/{n}, Cohen's kappa = {kappa:.2f}")
    counts = Counter(c["change"] for c in changes)
    print(f"Changes between consecutive runs: {counts['better']} better, {counts['worse']} worse, "
          f"{counts['still wrong']} still wrong")
    print(f"\nFiles written to {args.out_dir}/")


if __name__ == "__main__":
    main()
