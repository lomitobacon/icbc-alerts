# ICBC road test slot alerts

Checks ICBC Point Grey for Class 7 road test openings every few minutes on
GitHub Actions. When a slot appears between today and your end date, your
phone gets an ntfy push; tapping it opens the ICBC booking site. The checker
only reads. It never books, so you book the slot yourself.

## Setup (about 10 minutes)

### 1. Phone alerts
1. Install **ntfy** from the App Store or Google Play.
2. Tap **+** and subscribe to a topic name that nobody could guess, e.g.
   `icbc-howard-8f3k2q9z`. Anyone who knows the name can read your alerts,
   so make it random.
3. On iPhone, allow notifications for ntfy.

### 2. GitHub repo
1. On github.com, create a new repository, e.g. `icbc-alerts`.
   Make it **Public**. Public repos get unlimited free Actions minutes, while a
   private repo would use up its free 2,000 minutes in about a week. Your login
   details are stored as encrypted Secrets, which are never visible, even in a
   public repo.
2. Upload these files, keeping the folder structure:
   - `check_slots.py`
   - `.github/workflows/check.yml`
   - `.gitignore`
   - `README.md`

   The simplest way is **Add file → Upload files**, then drag in the files.
   `.github` is a hidden folder on a Mac: press **Cmd+Shift+.** in Finder to
   show it.

### 3. Secrets (your ICBC login)
Repo → **Settings → Secrets and variables → Actions → Secrets → New repository secret**.
Add four:

| Name | Value |
|---|---|
| `ICBC_LAST_NAME` | your last name |
| `ICBC_LICENSE_NUMBER` | your driver's licence number |
| `ICBC_SECRET_WORD` | your ICBC keyword |
| `NTFY_TOPIC` | your ntfy topic name from step 1 |

### 4. Your date range
Same page, **Variables** tab → **New repository variable**:

| Name | Value |
|---|---|
| `END_DATE` | the latest date you'd accept, e.g. `2026-11-30` |

It alerts for any slot from today up to and including that date. To change the
range later, just edit this variable.

Optional variables:
- `LOCATION`: an office name to watch instead of `Point Grey`.
- `EXAM_TYPE`: use `5-R-1` for Class 5 instead of Class 7.

### 5. Test it
Repo → **Actions** tab → enable workflows if asked → **Check ICBC road test
slots** → **Run workflow**. After about 3 minutes, open the run. A working run
logs something like:

```
2026-11-02 14:05 Vancouver (Point Grey): 214 open, 3 on or before 2026-11-30, 3 new
```

The first run sends a push for every slot already in your range. After that,
you only get pushes for slots that newly appear.

## How it behaves
- Runs every 5 minutes, checking twice per run (2.5 min apart). GitHub often
  delays scheduled runs, so expect a check every few minutes most of the time,
  with occasional gaps of 10–20 minutes.
- One push per newly appeared slot. A slot that gets taken and then frees up
  again triggers another push.
- If checks start failing (wrong keyword, ICBC changes something, ICBC blocks
  GitHub), you get a single "ICBC checker failing" push, then a "working again"
  push once it recovers. GitHub also emails you about failed runs.

## Things to know
- **GitHub pauses scheduled workflows after 60 days with no repo activity.**
  Editing `END_DATE` doesn't count as activity, but any commit does (e.g. editing
  this README).
- **To stop it:** Actions tab → the workflow → **⋯ → Disable workflow**.
- Automated checking may go against ICBC's terms of use. This checks gently and
  never books, but that risk is yours to judge.
- If GitHub's schedule turns out too slow to catch same-week cancellations,
  the same script can run every 1–2 minutes on a small server.
