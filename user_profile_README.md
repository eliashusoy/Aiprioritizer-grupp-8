# Student profile (`user_profile.json`)

This is the same short sign-up form every student would fill in once when starting to use
the prioritizer. It is only used with `python prioritizer.py --profile user_profile.json`
to judge whether an announcement applies to you. Without `--profile`, it is ignored.

Replace every `"<FILL IN>"`. The program stops with an error if any value is still `"<FILL IN>"`
or empty. Do **not** add your name, student ID, email or anything else that identifies you.

| Field | What to write | Example |
|---|---|---|
| `student_type` | Your type of study | `"full-time local"`, `"exchange"`, `"postgraduate"` |
| `study_period` | When you study at CityU | `"Aug–Dec 2026"` |
| `programme` | Study programme / major | `"BBA Information Systems"` |
| `enrolled_courses` | List of the course codes you take this semester | `["GE2340", "CB4601", "MGT4309"]` |
| `residence` | Student hall name, or `"off campus"` | `"Student Residence Hall 17"` |
| `fees_paid_to_cityu` | Do you pay tuition fees to CityU? | `"yes"` or `"no"` (e.g. exchange students paying their home university) |
| `visa_or_entry_permit` | Your immigration status | `"student visa valid until end of study period"`, `"local, not needed"` |
| `work_or_internship_allowed_in_hk` | Are you allowed to work / intern in Hong Kong? | `"yes"` or `"no"` |
| `interested_in` | List of things you want to hear about | `["careers", "sports", "volunteering", "hall events"]` |

Lists use square brackets with each item in quotes, separated by commas.

When you run with a profile, an exact copy of the profile used is saved next to the
results (e.g. `results/results_personal_profile.json`), so it is documented which
profile the results come from.
