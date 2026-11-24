"""
AI-Powered Student Daily Prioritizer & Noise Filter - prototype
GE2340 Course Project, Phase 2

Reads university announcements from a CSV file and splits the work in two:
  1. DeepSeek interprets the text: importance, exact deadline, task, action, evidence
     (plus its own overall "llm_priority", kept only for comparison in the report).
  2. Python computes the FINAL priority from importance + time left until the
     deadline, relative to a reference date (see compute_priority).
Results are saved to a results CSV.

Optional personalisation (controlled experiment): with --profile, ONE thing changes:
a student-profile block is appended to the system prompt. Model, temperature, JSON
format, rules and compute_priority are identical. Without --profile the system
prompt is byte-for-byte the same as before.

Usage:
    python prioritizer.py                              # sample_announcements.csv, reference = now
    python prioritizer.py my_data.csv                  # your own file
    python prioritizer.py --date received              # reference = each message's date_received at 09:00
    python prioritizer.py --date 2026-11-28            # simulate a specific day (09:00)
    python prioritizer.py --output results/x.csv       # write somewhere else than results.csv
    python prioritizer.py --profile user_profile.json  # personalised run (see user_profile_README.md)

Input CSV columns (required): id, source, date_received, subject, body
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
MODEL = "deepseek-flash"          # DeepSeek V4.1 Flash
BASE_URL = "https://api.deepseek.com"
DEFAULT_INPUT_FILE = "sample_announcements.csv"
OUTPUT_FILE = "results.csv"
TIMEZONE = ZoneInfo("Asia/Hong_Kong")
DATE_FORMAT = "%Y-%m-%d %H:%M"    # format of deadlines from the LLM and of reference dates
REFERENCE_HOUR = 9                # "--date received" / "--date YYYY-MM-DD" use 09:00 that day

IMPORTANCE_LEVELS = ["Low", "Medium", "High"]
PRIORITY_LEVELS = ["Low", "Medium", "High", "Urgent"]

# Urgency thresholds used by compute_priority
SHORT_WINDOW = timedelta(hours=48)   # deadline within 48 h  -> escalate one level
MEDIUM_WINDOW = timedelta(days=7)    # deadline within 7 days -> keep importance

# importance -> (<= SHORT_WINDOW, <= MEDIUM_WINDOW, > MEDIUM_WINDOW)
PRIORITY_MATRIX = {
    "Low":    ("Medium", "Low",    "Low"),
    "Medium": ("High",   "Medium", "Medium"),
    "High":   ("Urgent", "High",   "High"),
}

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an assistant that helps university students at City University of Hong Kong
prioritize announcements from Canvas, email, the AIMS portal, student halls and university offices.

For each announcement, return two separate judgements:

1. "importance" = how serious the consequences are if the student ignores the announcement,
   INDEPENDENT of how close the deadline is:
   - High: affects grades/coursework, course registration, visa/enrolment status, or fines.
   - Medium: relevant information or optional action with some benefit (e.g. a workshop,
     survey with incentive, schedule change that does not require action).
   - Low: general information, newsletters, promotions, events, reminders of rules that need no action.

2. "llm_priority" = your own overall priority relative to the received date:
   - Urgent: requires action within 48 hours of the received date, OR missing it has serious
     consequences (grades, course registration, visa/enrolment status, fines).
   - High: requires action from the student with a deadline within roughly 2 weeks, or affects grades/coursework.
   - Medium: relevant information or optional action with some benefit.
   - Low: general information, newsletters, promotions, events, reminders of rules that need no action.

Return ONLY a JSON object with exactly these keys:
{
  "importance": "Low" | "Medium" | "High",
  "llm_priority": "Low" | "Medium" | "High" | "Urgent",
  "deadline": "YYYY-MM-DD HH:MM" or null if there is no deadline,
  "task": short description of what the student must do (max 15 words), or null if nothing,
  "suggested_action": one concrete next step for the student (max 20 words),
  "evidence": the exact short phrase from the announcement that the deadline/importance is based on
}

Rules:
- Resolve relative dates ("this Friday", "within 3 days") to an exact date using the received date.
- If a time is not given but a date is, use 23:59.
- Do not invent deadlines that are not stated in the text.
- Words like "Important" in the subject do not automatically mean high importance; judge the actual content."""


# ---------------------------------------------------------------------------
# Optional student profile (only used with --profile)
# ---------------------------------------------------------------------------
PROFILE_FIELDS = [
    "student_type",
    "study_period",
    "programme",
    "enrolled_courses",
    "residence",
    "fees_paid_to_cityu",
    "visa_or_entry_permit",
    "work_or_internship_allowed_in_hk",
    "interested_in",
]
FILL_IN = "<FILL IN>"


class ProfileError(Exception):
    """The profile file is missing, malformed or not filled in."""


def load_profile(path):
    """Read and check a profile JSON file. Returns the profile as a dict."""
    try:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
    except OSError as e:
        raise ProfileError(f"cannot open profile file {path}: {e}")
    except json.JSONDecodeError as e:
        raise ProfileError(f"{path} is not valid JSON: {e}")
    if not isinstance(profile, dict):
        raise ProfileError(f"{path} must contain a JSON object with the profile fields")

    missing = [k for k in PROFILE_FIELDS if k not in profile]
    if missing:
        raise ProfileError(f"{path} is missing these fields: {', '.join(missing)}")

    def unfilled(value):
        if isinstance(value, list):
            return not value or any(unfilled(v) for v in value)
        return value is None or str(value).strip() in ("", FILL_IN) or FILL_IN in str(value)

    not_filled = [k for k in profile if unfilled(profile[k])]
    if not_filled:
        raise ProfileError(
            f"{path} is not filled in yet. Replace \"{FILL_IN}\" (or empty values) in: "
            f"{', '.join(not_filled)}. See user_profile_README.md."
        )
    return profile


def format_profile_value(value):
    return ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)


def build_system_prompt(profile=None):
    """SYSTEM_PROMPT unchanged without a profile; with a profile, one block appended."""
    if not profile:
        return SYSTEM_PROMPT
    lines = "\n".join(f"- {key}: {format_profile_value(value)}" for key, value in profile.items())
    return (
        SYSTEM_PROMPT
        + "\n\nStudent profile (provided by the student at sign-up):\n"
        + lines
        + "\n\nUse the profile only to judge whether the announcement applies to this student.\n"
        "If it clearly does not apply (e.g. it concerns a course, fee, status or\n"
        "opportunity that the profile shows is not relevant), set importance to Low and\n"
        "explain why in relevance_reason. If you are unsure, do NOT lower the importance –\n"
        "missing something important is worse than an extra reminder.\n"
        "\n"
        "In addition to the keys above, the JSON object must also contain:\n"
        '  "relevant_to_user": true or false,\n'
        '  "relevance_reason": short reason based on the profile (max 15 words)'
    )


def build_user_message(row):
    return (
        f"Received date: {row['date_received']}\n"
        f"Source: {row['source']}\n"
        f"Subject: {row['subject']}\n\n"
        f"Announcement:\n{row['body']}"
    )


def classify(client, row, system_prompt=SYSTEM_PROMPT, profile_used=False):
    """Send one announcement to the LLM and return the parsed JSON result."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_message(row)},
        ],
        response_format={"type": "json_object"},   # forces valid JSON output
        temperature=0,                             # as deterministic as possible
        extra_body={"thinking": {"type": "disabled"}},  # faster + cheaper; try "enabled" as an experiment
    )
    result = validate_result(json.loads(response.choices[0].message.content), profile_used)

    usage = response.usage
    result["input_tokens"] = usage.prompt_tokens
    result["output_tokens"] = usage.completion_tokens
    return result


def validate_result(result, profile_used=False):
    """Basic validation so bad outputs are visible instead of silently wrong."""
    if result.get("importance") not in IMPORTANCE_LEVELS:
        result["importance"] = f"INVALID({result.get('importance')})"
    if result.get("llm_priority") not in PRIORITY_LEVELS:
        result["llm_priority"] = f"INVALID({result.get('llm_priority')})"
    for key in ("deadline", "task", "suggested_action", "evidence"):
        result.setdefault(key, None)

    if not profile_used:
        # Not asked for without a profile: always null, whatever the model returned
        result["relevant_to_user"] = None
        result["relevance_reason"] = None
    else:
        if not isinstance(result.get("relevant_to_user"), bool):
            result["relevant_to_user"] = f"INVALID({result.get('relevant_to_user')})"
        reason = result.get("relevance_reason")
        result["relevance_reason"] = reason if isinstance(reason, str) and reason.strip() else None
    return result


# ---------------------------------------------------------------------------
# Rule-based priority (pure Python, no API calls)
# ---------------------------------------------------------------------------
def compute_priority(importance, deadline, reference_dt):
    """Combine the LLM's importance with time left until the deadline.

    importance   : "Low" | "Medium" | "High" (anything else is passed through unchanged)
    deadline     : "YYYY-MM-DD HH:MM" string, datetime, or None
    reference_dt : timezone-aware datetime ("now" for the student)

    Returns (final_priority, hours_left). hours_left is None when there is no
    usable deadline, and negative when the deadline has passed.
    """
    if importance not in PRIORITY_MATRIX:
        return importance, None        # e.g. INVALID(...) or ERROR: keep it visible
    if not deadline:
        return importance, None

    if isinstance(deadline, str):
        try:
            deadline = datetime.strptime(deadline.strip(), DATE_FORMAT)
        except ValueError:
            return importance, None    # unparseable deadline: fall back to importance
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=TIMEZONE)

    time_left = deadline - reference_dt
    hours_left = round(time_left.total_seconds() / 3600, 1)

    if time_left < timedelta(0):
        return "Expired", hours_left
    if time_left <= SHORT_WINDOW:
        column = 0
    elif time_left <= MEDIUM_WINDOW:
        column = 1
    else:
        column = 2
    return PRIORITY_MATRIX[importance][column], hours_left


def parse_date_option(value):
    """argparse type for --date: 'today', 'received' or 'YYYY-MM-DD'."""
    if value in ("today", "received"):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(hour=REFERENCE_HOUR, tzinfo=TIMEZONE)
    except ValueError:
        raise argparse.ArgumentTypeError("use 'today', 'received' or a date like 2026-11-28")


def reference_for_row(date_option, row, now):
    """Return the reference datetime to use for one announcement."""
    if date_option == "today":
        return now
    if date_option == "received":
        received = datetime.strptime(row["date_received"].strip()[:10], "%Y-%m-%d")
        return received.replace(hour=REFERENCE_HOUR, tzinfo=TIMEZONE)
    return date_option                 # fixed simulated date


def main():
    parser = argparse.ArgumentParser(description="Prioritize university announcements with DeepSeek + rules.")
    parser.add_argument("input_file", nargs="?", default=DEFAULT_INPUT_FILE,
                        help=f"input CSV (default: {DEFAULT_INPUT_FILE})")
    parser.add_argument("--date", type=parse_date_option, default="today",
                        help="reference date: 'today' (default), 'received', or YYYY-MM-DD")
    parser.add_argument("--profile", default="none",
                        help="student profile JSON (default: none = no personalisation)")
    parser.add_argument("--output", default=OUTPUT_FILE,
                        help=f"output CSV (default: {OUTPUT_FILE})")
    args = parser.parse_args()

    profile = None
    profile_used = "none"
    if args.profile.lower() != "none":
        try:
            profile = load_profile(args.profile)
        except ProfileError as e:
            sys.exit(f"Error: {e}")
        profile_used = os.path.basename(args.profile)
    system_prompt = build_system_prompt(profile)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        sys.exit("Error: set the DEEPSEEK_API_KEY environment variable first (see the guide).")

    client = OpenAI(api_key=api_key, base_url=BASE_URL)

    with open(args.input_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    now = datetime.now(TIMEZONE)
    if args.date == "today":
        reference_text = f"today ({now.strftime(DATE_FORMAT)} HKT)"
    elif args.date == "received":
        reference_text = f"each message's date_received at {REFERENCE_HOUR:02d}:00 HKT"
    else:
        reference_text = f"simulated {args.date.strftime(DATE_FORMAT)} HKT"

    print(f"Reference date: {reference_text}")
    print(f"Profile       : {profile_used}")
    print(f"Classifying {len(rows)} announcements from {args.input_file} with {MODEL}...\n")

    output_rows = []
    total_in = total_out = 0
    for row in rows:
        start = time.time()
        try:
            result = classify(client, row, system_prompt, profile_used=profile is not None)
        except Exception as e:  # keep going if one message fails
            print(f"[{row['id']}] ERROR: {e}")
            result = {"importance": "ERROR", "llm_priority": "ERROR", "deadline": None,
                      "task": None, "suggested_action": str(e), "evidence": None,
                      "relevant_to_user": None, "relevance_reason": None,
                      "input_tokens": 0, "output_tokens": 0}
        seconds = round(time.time() - start, 2)

        reference_dt = reference_for_row(args.date, row, now)
        final_priority, hours_left = compute_priority(result["importance"], result["deadline"], reference_dt)

        total_in += result["input_tokens"]
        total_out += result["output_tokens"]

        print(f"[{row['id']}] {row['subject']}")
        print(f"   Importance     : {result['importance']}")
        print(f"   LLM priority   : {result['llm_priority']}")
        print(f"   FINAL priority : {final_priority}")
        print(f"   Deadline       : {result['deadline']}")
        print(f"   Hours left     : {hours_left}")
        print(f"   Task           : {result['task']}")
        print(f"   Action         : {result['suggested_action']}")
        if profile is not None:
            print(f"   Relevant to you: {result['relevant_to_user']} ({result['relevance_reason']})")
        print(f"   Evidence       : {result['evidence']}  ({seconds}s)\n")

        output_rows.append({
            "id": row["id"],
            "source": row["source"],
            "subject": row["subject"],
            "reference_date": reference_dt.strftime(DATE_FORMAT),
            "ai_importance": result["importance"],
            "ai_llm_priority": result["llm_priority"],
            "final_priority": final_priority,
            "ai_deadline": result["deadline"],
            "hours_left": hours_left,
            "ai_task": result["task"],
            "ai_suggested_action": result["suggested_action"],
            "ai_evidence": result["evidence"],
            "profile_used": profile_used,
            "ai_relevant_to_user": result["relevant_to_user"],
            "ai_relevance_reason": result["relevance_reason"],
            "seconds": seconds,
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
        })

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_rows[0].keys())
        writer.writeheader()
        writer.writerows(output_rows)

    # Document exactly which profile these results come from
    profile_copy = None
    if profile is not None:
        profile_copy = os.path.splitext(args.output)[0] + "_profile.json"
        with open(profile_copy, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

    # Peak price for deepseek-flash: $0.30 / 1M input, $1.20 / 1M output
    cost = total_in / 1e6 * 0.30 + total_out / 1e6 * 1.20
    print(f"Done. Results saved to {args.output}")
    if profile_copy:
        print(f"Profile used saved to {profile_copy}")
    print(f"Tokens used: {total_in} in / {total_out} out  ->  approx. ${cost:.4f}")


if __name__ == "__main__":
    main()
