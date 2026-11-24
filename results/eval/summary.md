# Evaluation against the answer key

Urgent counted as High in the main numbers: **yes**. Expired counts as wrong unless the key also says Expired.

## Main results (all mails)

| Run | n | Priority correct (hybrid) | LLM alone | Importance correct | High recall | High precision | Noise filtered (key Low → AI Low) |
|---|---|---|---|---|---|---|---|
| Run 1: no profile | 33 | 20/33 (61%) | 20/33 (61%) | 22/33 (67%) | 10/11 (91%) | 10/15 (67%) | 9/20 (45%) |
| Run 2: profile v1 | 33 | 25/33 (76%) | 25/33 (76%) | 27/33 (82%) | 9/11 (82%) | 9/12 (75%) | 16/20 (80%) |
| Run 3: profile v2 | 33 | 24/33 (73%) | 24/33 (73%) | 27/33 (82%) | 10/11 (91%) | 10/13 (77%) | 14/20 (70%) |

## Real vs. synthetic mails (priority correct, hybrid)

| Run | Real | Synthetic |
|---|---|---|
| Run 1: no profile | 14/23 (61%) | 6/10 (60%) |
| Run 2: profile v1 | 18/23 (78%) | 7/10 (70%) |
| Run 3: profile v2 | 17/23 (74%) | 7/10 (70%) |

## Strict comparison (Urgent ≠ High)

| Run | Priority correct (hybrid) | LLM alone |
|---|---|---|
| Run 1: no profile | 18/33 (55%) | 17/33 (52%) |
| Run 2: profile v1 | 23/33 (70%) | 21/33 (64%) |
| Run 3: profile v2 | 22/33 (67%) | 20/33 (61%) |

## Errors: over- vs. under-prioritised

| Run | Errors | AI too high | AI too low | Other (Expired/invalid) |
|---|---|---|---|---|
| Run 1: no profile | 13 | 11 | 2 | 0 |
| Run 2: profile v1 | 8 | 5 | 3 | 0 |
| Run 3: profile v2 | 9 | 7 | 2 | 0 |

## Missed High and false alarms

- **Run 1: no profile**: missed High: R25; false alarms: R03, S01, S03, R24, R26
- **Run 2: profile v1**: missed High: R04, R25; false alarms: S01, R17, R24
- **Run 3: profile v2**: missed High: R25; false alarms: S01, R17, R24

## Deadlines

| Run | Exact | Same date, other time | Wrong date | Both empty | Missed | Extra |
|---|---|---|---|---|---|---|
| Run 1: no profile | 16 | 0 | 0 | 14 | 1 | 2 |
| Run 2: profile v1 | 17 | 0 | 0 | 15 | 0 | 1 |
| Run 3: profile v2 | 17 | 0 | 0 | 15 | 0 | 1 |

'Same date' here means same day but a different time; same day in total = exact + same date.

## Cost and time

| Run | Input tokens | Output tokens | Cost (USD) | Avg. seconds per mail |
|---|---|---|---|---|
| Run 1: no profile | 22907 | 2812 | 0.0102 | 1.48 |
| Run 2: profile v1 | 30794 | 3807 | 0.0138 | 1.51 |
| Run 3: profile v2 | 31256 | 3784 | 0.0139 | 1.62 |

## Answer key: AI-assisted label vs. final label

label_priority_AI vs. label_priority_final on 33 mails: agreement 24/33 (73%), Cohen's kappa = 0.51.
