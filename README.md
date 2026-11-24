# AI-Powered Student Daily Prioritizer & Noise Filter

GE2340 course project, City University of Hong Kong, Semester A 2026/27.

The prototype sorts a student's university announcements by urgency and filters out noise.
A large language model (DeepSeek) reads each announcement and extracts its importance,
deadline, task, a suggested next action and the evidence sentence it based this on. A fixed
Python rule then computes the final priority from the importance and the time left to the
deadline, and a local HTML dashboard shows the prioritised inbox.

Team: Group 8

## 1. How it works

1. **Input:** a CSV file with one announcement per row (`ai_input.csv` for our evaluation).
2. **LLM step** (`prioritizer.py`, `classify()`): each announcement is sent to DeepSeek
   (`deepseek-flash`, temperature 0, JSON output) together with the system prompt
   (`SYSTEM_PROMPT` in `prioritizer.py`).
3. **JSON answer:** `importance`, `llm_priority`, `deadline`, `task`, `suggested_action`,
   `evidence` (plus `relevant_to_user` and `relevance_reason` when a profile is used).
   Invalid values are marked `INVALID(...)` instead of being silently accepted.
4. **Rule step** (`compute_priority()`): Python combines `importance` with the time left to
   the deadline and produces `final_priority`.
5. **Output:** one row per announcement in a results CSV (default `results.csv`).
6. **Dashboard** (`build_dashboard.py`) and **evaluation** against the answer key (`evaluate.py`).

The LLM's own `llm_priority` is stored only to compare "LLM alone" with the hybrid
approach; it does not affect `final_priority`.

### Priority rule

| Importance \ time left | ≤ 48 h | ≤ 7 days | > 7 days |
|---|---|---|---|
| Low    | Medium | Low    | Low    |
| Medium | High   | Medium | Medium |
| High   | Urgent | High   | High   |

- No deadline: final priority = importance.
- Deadline already passed: `Expired`.
- Boundaries are inclusive (exactly 48 h counts as ≤ 48 h).
- All times are in the Asia/Hong_Kong time zone.
- The thresholds and the table are constants at the top of `prioritizer.py`
  (`SHORT_WINDOW`, `MEDIUM_WINDOW`, `PRIORITY_MATRIX`). The dashboard reads the same constants.

## 2. Requirements and installation

Python 3.11 or newer (developed and tested with Python 3.14.6 on macOS).

```bash
cd prototype
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` pins the tested versions of `openai`, `python-dotenv` and `matplotlib`,
and adds `tzdata` on Windows (needed for the Hong Kong time zone there).

## 3. API key

Create a file named `.env` in the `prototype` folder with one line:

```
DEEPSEEK_API_KEY=your-key-here
```

The key is loaded automatically by `python-dotenv`. `.env` is listed in `.gitignore` and must
never be committed or shared. Only `prioritizer.py` needs the key; the dashboard, the
evaluation and the tests run without it.

## 4. Input data format

**Announcements CSV** (input to `prioritizer.py`), required columns:

| Column | Content |
|---|---|
| `id` | Unique id, e.g. `R01` (real) or `S01` (synthetic) |
| `source` | Sender, e.g. `Canvas (GE2340)`, `Student Residence Office (Hall)` |
| `date_received` | `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` |
| `subject` | Subject line |
| `body` | Full text of the announcement |

The received date is passed to the model as text so it can resolve relative dates
("this Friday"). With `--date received` only the date part is used, at 09:00 Hong Kong time.

**Answer key** `fasit.csv` (used only by `evaluate.py`), columns used:

| Column | Content |
|---|---|
| `id` | Matches `id` in the announcements and results |
| `origin` | `real` or `synthetic` |
| `include_in_eval` | `yes` / `no` |
| `label_importance` | `Low` / `Medium` / `High` |
| `label_priority_final` | Final human label: `Low` / `Medium` / `High` (no `Urgent`) |
| `label_priority_AI` | Label suggested with AI help before human review (used for agreement/kappa) |
| `label_deadline` | `YYYY-MM-DD HH:MM`, or empty if there is no deadline |

The answer key is never sent to the model; `prioritizer.py` does not read it.

## 5. Running the prioritizer

```bash
python prioritizer.py [input_file] [--date DATE] [--profile FILE] [--output FILE]
```

| Option | Default | Meaning |
|---|---|---|
| `input_file` | `sample_announcements.csv` | Announcements CSV |
| `--date today` | yes | Reference time = now (Hong Kong time) |
| `--date received` | | Reference time = each announcement's `date_received` at 09:00. Used for evaluation, so deadlines are judged as on the day the email arrived |
| `--date YYYY-MM-DD` | | Simulate a specific day at 09:00 (for demos) |
| `--profile FILE` | `none` | Optional student profile JSON (section 6). `none` = no personalisation |
| `--output FILE` | `results.csv` | Results CSV. Folders are created if needed |

The commands used for our three runs:

```bash
# Run 1: no profile
python prioritizer.py ai_input.csv --date received --output results/results_generic.csv

# Run 2: incomplete profile
python prioritizer.py ai_input.csv --date received --profile user_profile.json --output results/results_personal.csv

# Run 3: corrected profile
python prioritizer.py ai_input.csv --date received --profile user_profile.json --output results/results_personal_v2.csv
```

Runs 2 and 3 used different versions of `user_profile.json`. The exact profile behind each
run is saved next to its results (`results/results_personal_profile.json` and
`results/results_personal_v2_profile.json`); pass that file to `--profile` to repeat a run.
Even at temperature 0 the model is not guaranteed to be fully deterministic, so a repeated
run may differ in a few rows.

Cost and time for the 33 emails: about USD 0.010 (no profile) to USD 0.014 (with profile)
per run, and about 1.5 s per email.

## 6. User profile (optional)

With `--profile`, the only change to the experiment is one block appended to the system
prompt. Model, temperature, JSON format and `compute_priority` stay identical, and without
`--profile` the prompt is byte-for-byte the same (checked by a test). The model then also
returns `relevant_to_user` and `relevance_reason`.

Fields in `user_profile.json` (explained in `user_profile_README.md`):
`student_type`, `study_period`, `programme`, `enrolled_courses`, `residence`,
`fees_paid_to_cityu`, `visa_or_entry_permit`, `work_or_internship_allowed_in_hk`,
`interested_in`.

The program stops with an error if a field is missing, empty or still `"<FILL IN>"`.
The profile must not contain names, student IDs, email addresses or other identifying details.

## 7. Dashboard

```bash
python build_dashboard.py results/results_personal_v2.csv ai_input.csv
open results/dashboard.html            # macOS; or double-click the file
```

Arguments: results CSV (default `results.csv`) and announcements CSV (default
`announcements.csv`, falling back to `sample_announcements.csv`). `dashboard.html` is written
next to the results file. It is one self-contained file with no external resources or
network calls; no server is needed. Rebuild it after every new prioritizer run.

The page has three tabs:

- **Inbox:** the prioritised announcements (sections below).
- **How it works:** the problem, the four-step pipeline, the priority rule table, a
  step-by-step trace of one chosen announcement (input, the model's JSON, the rule result)
  and the profile used, if `<results>_profile.json` exists next to the results file.
- **Evaluation:** the numbers from `eval/summary.csv` next to the results file (run
  `evaluate.py` first), including the confusion matrices. Missed and false-alarm ids link to
  the inbox.

Inbox sections:

- **Needs your attention now** (Urgent)
- **Due soon** (High)
- **Worth reading** (Medium)
- **Filtered out** (Low, collapsed). Also holds announcements the profile marked as not
  relevant, with the reason.
- **Past deadline** (Expired, collapsed)

Groups are sorted by nearest deadline. Clicking a message shows the original text with the
evidence sentence highlighted, plus the importance, the rule result and what the LLM alone said.

The **Viewing as** date picker recalculates all priorities in the browser for another day
(09:00 Hong Kong time), using the same rule. The page can also be opened at a given state,
e.g. `dashboard.html?date=2026-11-29&open=S05`, and a tab can be chosen with `#inbox`,
`#how` or `#eval` (e.g. `dashboard.html?date=2026-11-20#eval`).

## 8. Evaluation

No API calls. Command for the three runs:

```bash
python evaluate.py --fasit fasit.csv \
  --run "Run 1: no profile=results/results_generic.csv" \
  --run "Run 2: profile v1=results/results_personal.csv" \
  --run "Run 3: profile v2=results/results_personal_v2.csv"
```

More runs can be added with further `--run "Name=file"` arguments. Only rows with
`include_in_eval = yes` that also exist in the results file are evaluated; skipped ids are
printed.

**Urgent counted as High:** the answer key has no `Urgent` level, so by default the AI's
`Urgent` is treated as `High` in the main numbers. A strict comparison (Urgent ≠ High) is
always reported as well, and `--no-collapse-urgent` makes it the main comparison. `Expired`
counts as wrong unless the key also says `Expired`.

Output in `results/eval/` (overwritten on every run):

| File | Content |
|---|---|
| `summary.md` | Readable report: accuracy (hybrid vs. LLM alone), importance accuracy, High recall/precision with missed and false-alarm ids, noise filter, over- vs. under-prioritisation, deadlines, cost and time, real vs. synthetic, strict comparison, agreement and Cohen's kappa between `label_priority_AI` and `label_priority_final` |
| `summary.csv` | The same numbers, one row per run and subset (all / real / synthetic) |
| `summary_table.tex` | Main table for the report (LaTeX, requires `\usepackage{booktabs}`) |
| `confusion_<run>.png` | Confusion matrix of final priority vs. answer key |
| `errors.csv` | One row per wrong priority per run, with direction (over/under) |
| `changes.csv` | Emails whose priority changed between consecutive runs: better / worse / still wrong |

## 9. Tests

No API key or API calls needed:

```bash
python test_priority.py     # priority rule, unchanged prompt without profile, profile checks
python test_evaluate.py     # accuracy, recall, deadline comparison, Urgent -> High
```

## 10. Repository structure

```
prototype/
├── prioritizer.py            LLM step + priority rule; writes the results CSV
├── build_dashboard.py        Builds the self-contained dashboard.html
├── evaluate.py               Compares runs with the answer key; writes results/eval/
├── test_priority.py          Tests for prioritizer.py
├── test_evaluate.py          Tests for evaluate.py
├── ai_input.csv              The 33 anonymised announcements used in the evaluation
├── fasit.csv                 Answer key (human labels)
├── sample_announcements.csv  Four short examples for a quick test
├── user_profile.json         Student profile used with --profile
├── user_profile_README.md    Explanation of the profile fields
├── requirements.txt          Python dependencies
├── results/                  Results of the three runs and the profiles used
│   └── eval/                 Evaluation output (tables, figures, error lists)
├── .env                      API key (not in git)
└── .gitignore
```

## 11. Data and privacy

The 23 real emails are included in this repository (`ai_input.csv`) in anonymised form:
names, student IDs, personal email addresses, phone numbers, codes, our team number and our
hall and floor are replaced with `[NAME]`, `[SID]`, `[EMAIL]`, `[PHONE]`, `[CODE]`, `[TEAM]`,
`[HALL]` and `[FLOOR]`. All data in this repository is anonymised. Public office addresses and
phone numbers of university units are kept. 10 of the
33 emails are synthetic and were written with an LLM to test difficult cases
(`origin = synthetic` in `fasit.csv`).

The dashboard runs entirely locally; only `prioritizer.py` sends the announcement text (and
the profile, if used) to the DeepSeek API.

## 12. Use of AI tools

Parts of the code were written with the help of Claude Code (vibe coding is permitted in
GE2340), and the LLM used by the system itself is DeepSeek.
