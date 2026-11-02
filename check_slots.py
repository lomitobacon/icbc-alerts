#!/usr/bin/env python3
"""Check ICBC for open road-test slots and alert by SMS (Twilio) and/or ntfy.

Read-only: logs in, lists available appointments, never books anything.
Uses only the Python standard library.

Environment:
  ICBC_LAST_NAME, ICBC_LICENCE, ICBC_KEYWORD   login (GitHub Secrets)
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
  TWILIO_FROM, SMS_TO                          SMS alerts; SMS_TO is comma-separated
  NTFY_TOPIC                                   ntfy push alerts
  Alerts go to every channel that is configured.
  END_DATE        last acceptable test date, YYYY-MM-DD (required)
  LOCATION        office name to match, default "Point Grey"
  EXAM_TYPE       default "7-R-1" (Class 7). Class 5 is "5-R-1".
  STATE_FILE      where seen slots are remembered, default state.json
  CHECKS          how many checks per run, default 1
  CHECK_INTERVAL  seconds between checks in one run, default 150
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

API = os.environ.get("ICBC_API", "https://onlinebusiness.icbc.com/deas-api/v1")
NTFY = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
TWILIO = os.environ.get("TWILIO_API", "https://api.twilio.com")
BOOKING_URL = "https://onlinebusiness.icbc.com/webdeas-ui/home"
TZ = ZoneInfo("America/Vancouver")
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Cache-control": "no-cache, no-store",
    "Origin": "https://onlinebusiness.icbc.com",
    "Referer": "https://onlinebusiness.icbc.com/webdeas-ui/login;type=driver",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
}


class CheckError(Exception):
    pass


def env(name, default=None):
    value = os.environ.get(name, "").strip() or default
    if value is None:
        raise CheckError(f"Missing setting {name}")
    return value


def call(method, path, body, token=None):
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(), headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode() or "null"
            return json.loads(raw), resp.headers
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise CheckError(f"{method} {path} failed: HTTP {e.code} {detail}") from None
    except urllib.error.URLError as e:
        raise CheckError(f"{method} {path} failed: {e.reason}") from None


def login():
    body, headers = call(
        "PUT",
        "/webLogin/webLogin",
        {
            "drvrLastName": env("ICBC_LAST_NAME"),
            "licenceNumber": env("ICBC_LICENCE"),
            "keyword": env("ICBC_KEYWORD"),
        },
    )
    token = headers.get("Authorization")
    if not token:
        raise CheckError("Login returned no token. Check the name, licence and keyword secrets.")
    return token, body or {}


def find_pos_id(token, exam_type, today, location):
    """Look up the office's posId by matching its name/address."""
    offices, _ = call("PUT", "/web/getPosByExam", {"examType": exam_type, "startDate": today}, token)
    needle = location.lower()
    for item in offices or []:
        pos = item.get("pos", item) if isinstance(item, dict) else {}
        if needle in json.dumps(item).lower() and pos.get("posId") is not None:
            return pos["posId"], pos.get("agency") or location
    raise CheckError(f"No ICBC office matching '{location}' offers exam {exam_type}")


def fetch_slots(token, user, pos_id, exam_type, today):
    slots, _ = call(
        "POST",
        "/web/getAvailableAppointments",
        {
            "aPosID": pos_id,
            "examType": exam_type,
            "examDate": today,
            "ignoreReserveTime": False,
            "prfDaysOfWeek": "[0,1,2,3,4,5,6]",
            "prfPartsOfDay": "[0,1]",
            "lastName": user.get("lastName") or env("ICBC_LAST_NAME"),
            "licenseNumber": user.get("licenseNumber") or env("ICBC_LICENCE"),
        },
        token,
    )
    result = []
    for s in slots or []:
        day = (s.get("appointmentDt") or {}).get("date")
        start = s.get("startTm")
        if day and start:
            result.append((day, start))
    return sorted(set(result))


def describe(day, start):
    d = date.fromisoformat(day)
    t = start
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(start, fmt).strftime("%-I:%M %p")
            break
        except ValueError:
            pass
    return f"{d:%a %b %-d} at {t}"


def send_ntfy(title, message, priority, tags):
    req = urllib.request.Request(
        f"{NTFY}/{env('NTFY_TOPIC')}",
        data=f"{message}\n\nTap to open ICBC booking.".encode(),
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": BOOKING_URL},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30):
        pass


def send_sms(title, message):
    sid = env("TWILIO_ACCOUNT_SID")
    auth = base64.b64encode(f"{sid}:{env('TWILIO_AUTH_TOKEN')}".encode()).decode()
    body = f"{title}\n{message}\nBook: {BOOKING_URL}"
    for to in env("SMS_TO").split(","):
        req = urllib.request.Request(
            f"{TWILIO}/2010-04-01/Accounts/{sid}/Messages.json",
            data=urllib.parse.urlencode({"To": to.strip(), "From": env("TWILIO_FROM"), "Body": body}).encode(),
            headers={"Authorization": f"Basic {auth}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30):
            pass


def notify(title, message, priority="high", tags="rotating_light"):
    """Send to every configured channel; raise CheckError if any fails."""
    channels = []
    if os.environ.get("NTFY_TOPIC", "").strip():
        channels.append(("ntfy", lambda: send_ntfy(title, message, priority, tags)))
    if os.environ.get("TWILIO_ACCOUNT_SID", "").strip():
        channels.append(("SMS", lambda: send_sms(title, message)))
    if not channels:
        raise CheckError("No alert channel set up (add the Twilio or NTFY_TOPIC secrets)")
    errors = []
    for name, send in channels:
        try:
            send()
        except urllib.error.HTTPError as e:
            errors.append(f"{name}: HTTP {e.code} {e.read().decode(errors='replace')[:200]}")
        except (urllib.error.URLError, CheckError) as e:
            errors.append(f"{name}: {e}")
    if errors:
        raise CheckError("Alert failed: " + "; ".join(errors))


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def slot_lines(slots, show_all_before, soonest=3, cap=30):
    """The 3 soonest slots, or every slot before `show_all_before` if there are more of those."""
    count = max(soonest, sum(date.fromisoformat(d) < show_all_before for d, _ in slots))
    shown = min(count, cap)  # cap keeps a text under Twilio's 1,600-character limit
    lines = [describe(*s) for s in slots[:shown]]
    if len(slots) > shown:
        lines.append(f"...and {len(slots) - shown} more")
    return lines


def eligible_from(user, exam_type, earliest):
    """Later of `earliest` and the driver's earliest eligible date (eed) for this exam."""
    exams = user.get("eligibleExams") or []
    for exam in exams:
        if exam.get("code") == exam_type:
            eed = (exam.get("eed") or {}).get("date")
            return max(earliest, date.fromisoformat(eed)) if eed else earliest
    codes = ", ".join(e.get("code", "?") for e in exams) or "none"
    raise CheckError(f"ICBC says you aren't eligible to book {exam_type} (eligible: {codes})")


def check_once(state):
    exam_type = env("EXAM_TYPE", "7-R-1")
    location = env("LOCATION", "Point Grey")
    end_date = date.fromisoformat(env("END_DATE"))
    today = datetime.now(TZ).date()

    token, user = login()
    # Search like the booking site does: from tomorrow or your earliest eligible
    # exam date, whichever is later. Earlier slots can't be booked by you.
    start = eligible_from(user, exam_type, today + timedelta(days=1))
    key = f"{location}|{exam_type}"
    if state.get("pos_key") != key:
        state["pos_id"], state["pos_name"] = find_pos_id(token, exam_type, start.isoformat(), location)
        state["pos_key"] = key

    slots = fetch_slots(token, user, state["pos_id"], exam_type, start.isoformat())
    wanted = [s for s in slots if start <= date.fromisoformat(s[0]) <= end_date]
    seen = {tuple(s) for s in state.get("seen", [])}
    new = [s for s in wanted if s not in seen]

    print(f"{datetime.now(TZ):%Y-%m-%d %H:%M} {state['pos_name']}: searching from {start}, "
          f"{len(slots)} open, {len(wanted)} on or before {end_date}, {len(new)} new")
    if slots:
        print("  earliest: " + "; ".join(describe(*s) for s in slots[:3]))
    show_all_before = date.fromisoformat(env("SHOW_ALL_BEFORE", "2026-12-01"))
    if env("SUMMARY", "false") == "true":
        # Manual run asking for everything currently open, not just new slots.
        lines = slot_lines(wanted, show_all_before)
        if not wanted:
            lines = [f"None on or before {end_date:%b %-d}."]
            if slots:
                lines.append(f"Earliest open: {describe(*slots[0])}")
        notify(f"ICBC: {len(wanted)} open slot{'' if len(wanted) == 1 else 's'} at {location}, "
               f"{start:%b %-d} to {end_date:%b %-d}", "\n".join(lines), priority="default", tags="calendar")
    elif new:
        notify(
            f"ICBC: {len(new)} new road test slot{'s' if len(new) > 1 else ''} at {location}",
            "\n".join(slot_lines(new, show_all_before)),
        )
    # Remember only slots still open, so a slot that is taken and freed again alerts again.
    # Saved after alerting, so a failed alert is retried on the next check.
    state["seen"] = [list(s) for s in wanted]


def main():
    state_file = env("STATE_FILE", "state.json")
    checks = int(env("CHECKS", "1"))
    interval = int(env("CHECK_INTERVAL", "150"))
    state = load_state(state_file)
    failed = False

    for i in range(checks):
        if i:
            time.sleep(interval)
        try:
            try:
                check_once(state)
            except CheckError as e:
                # ICBC sometimes refuses a single request (e.g. a one-off HTTP 403), so retry once.
                print(f"Retrying in 30s after: {e}", file=sys.stderr)
                time.sleep(30)
                check_once(state)
            if state.get("error"):
                notify("ICBC checker working again", "Slot checks are succeeding again.",
                       priority="low", tags="white_check_mark")
                state["error"] = None
        except Exception as e:
            # Anything unexpected too (e.g. ICBC changing its data format), so it never fails silently.
            failed = True
            err = str(e) if isinstance(e, CheckError) else f"Unexpected {type(e).__name__}: {e}"
            print(f"ERROR: {err}", file=sys.stderr)
            # Alert once when it starts failing, not on every run.
            if not state.get("error"):
                try:
                    notify("ICBC checker failing", err, tags="warning")
                except Exception as ne:
                    print(f"Could not send failure alert: {ne}", file=sys.stderr)
            state["error"] = err
        save_state(state_file, state)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--alert"]:
        notify("ICBC checker failing", " ".join(sys.argv[2:]), tags="warning")
    else:
        main()
