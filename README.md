# ICBC road test slot alerts

Checks ICBC Point Grey for Class 7 road test openings every few minutes on
GitHub Actions. When a slot appears between today and your end date, it texts
each phone number you list. The checker only reads. It never books, so you book
the slot yourself.

Repo: https://github.com/lomitobacon/icbc-alerts

## Settings
Repo → **Settings → Secrets and variables → Actions**.

**Secrets**

| Name | Value |
|---|---|
| `ICBC_LAST_NAME` | your last name |
| `ICBC_LICENSE_NUMBER` | your driver's licence number |
| `ICBC_SECRET_WORD` | your ICBC keyword |
| `TWILIO_ACCOUNT_SID` | from the Twilio console, starts with `AC` |
| `TWILIO_AUTH_TOKEN` | from the Twilio console |
| `TWILIO_FROM` | your Twilio phone number, e.g. `+16045550100` |
| `SMS_TO` | numbers to text, comma-separated, e.g. `+16045551111,+16045552222` |
| `NTFY_TOPIC` | optional: an ntfy topic for app push alerts too. Delete this secret to turn ntfy off. |

**Variables**

| Name | Value |
|---|---|
| `END_DATE` | the latest date you'd accept, e.g. `2026-12-31` |
| `LOCATION` | optional: an office name instead of `Point Grey` |
| `EXAM_TYPE` | optional: `5-R-1` for Class 5 instead of Class 7 |

Alerts go to every channel that's set up: SMS if the Twilio secrets exist,
ntfy if `NTFY_TOPIC` exists.

## Twilio setup
1. Sign up at https://www.twilio.com/try-twilio. The trial includes free credit.
2. In the console, **Phone Numbers → Buy a number**. Pick a **Canada (+1 604)**
   number with SMS. A Canadian number avoids the US registration rules for
   texting.
3. **Phone Numbers → Verified Caller IDs → Add**: verify every number in
   `SMS_TO`. Each person gets a code by text. Trial accounts can only text
   verified numbers.
4. Copy the **Account SID** and **Auth Token** from the console home page into
   the secrets above.

Trial texts start with "Sent from your Twilio trial account". Upgrading (adding
a card) removes that, and costs roughly $1.50 CAD/month for the number plus
about 1¢ per text.

## How it behaves
- Runs every 5 minutes, checking twice per run (2.5 min apart). GitHub often
  delays scheduled runs, so expect a check every few minutes most of the time,
  with occasional gaps of 10–20 minutes.
- Sends one text per batch of newly appeared slots, listing up to 8 of them.
  A slot that gets taken and then frees up again alerts again.
- If a text fails to send, those slots are retried on the next check.
- If checks start failing (wrong keyword, ICBC changes something, ICBC blocks
  GitHub), you get one "ICBC checker failing" text, then a "working again"
  text once it recovers. GitHub also emails you about failed runs.
- To check by hand, or get a list of everything open right now: **Actions** tab → **Check ICBC road test slots** →
  **Run workflow**, and tick "Send all currently open slots" for the full list.

## Things to know
- **GitHub pauses scheduled workflows after 60 days with no repo activity.**
  Editing `END_DATE` doesn't count as activity, but any commit does.
- **To stop it:** Actions tab → the workflow → **⋯ → Disable workflow**.
- Automated checking may go against ICBC's terms of use. This checks gently and
  never books, but that risk is yours to judge.
