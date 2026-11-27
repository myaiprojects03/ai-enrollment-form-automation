# Raw samples

Upload these to see mapping and validation work on messy input (operator token from your .env):

```bash
export $(grep OPERATOR_TOKEN ../../.env)
curl -H "Authorization: Bearer $OPERATOR_TOKEN" -F target_form=riverside-enrollment \
     -F file=@riverside-export.csv localhost:8000/api/intake/upload
curl -H "Authorization: Bearer $OPERATOR_TOKEN" -F target_form=harbour-membership \
     -F file=@harbour-signups.json localhost:8000/api/intake/upload
curl -H "Authorization: Bearer $OPERATOR_TOKEN" -F target_form=riverside-enrollment \
     -F file=@intake-note.txt localhost:8000/api/intake/upload
```

| File | What it tests |
|---|---|
| `riverside-export.csv` | Export-style headers, full names, one-line addresses, a minor without the guardian's relationship, a day/month-ambiguous date, missing consent, a course typo, a returning student |
| `harbour-signups.json` | Nested objects, a family plan, a student card column with an unusual name (needs the AI), an emergency number that is the member's own, an under-16 who refused the terms |
| `intake-note.txt` | Free-text call notes: needs the AI mapper (set GROQ_API_KEY) |

Start dates in the JSON are a few weeks after November 2026; move them forward if they have passed.
All people, emails and numbers are made up.
