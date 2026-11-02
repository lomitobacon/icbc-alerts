#!/usr/bin/env python3
"""Check ICBC for open road-test slots and push new ones to ntfy.

Read-only: logs in, lists available appointments, never books anything.
Uses only the Python standard library.

Environment:
  ICBC_LAST_NAME, ICBC_LICENCE, ICBC_KEYWORD   login (GitHub Secrets)
  NTFY_TOPIC                                   ntfy topic name (GitHub Secret)
  END_DATE        last acceptable test date, YYYY-MM-DD (required)
  LOCATION        office name to match, default "Point Grey"
  EXAM_TYPE       default "7-R-1" (Class 7). Class 5 is "5-R-1".
  STATE_FILE      where seen slots are remembered, default state.json
  CHECKS          how many checks per run, default 1
  CHECK_INTERVAL  seconds between checks in one run, default 150
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from zoneinfo import ZoneInfo

API = os.environ.get("ICBC_API", "https://onlinebusiness.icbc.com/deas-api/v1")
NTFY = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
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


def notify(title, message, priority="high", tags="rotating_light"):
    req = urllib.request.Request(
        f"{NTFY}/{env('NTFY_TOPIC')}",
        data=message.encode(),
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": BOOKING_URL},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30):
        pass


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def check_once(state):
    exam_type = env("EXAM_TYPE", "7-R-1")
    location = env("LOCATION", "Point Grey")
    end_date = date.fromisoformat(env("END_DATE"))
    today = datetime.now(TZ).date()

    token, user = login()
    key = f"{location}|{exam_type}"
    if state.get("pos_key") != key:
        state["pos_id"], state["pos_name"] = find_pos_id(token, exam_type, today.isoformat(), location)
        state["pos_key"] = key

    slots = fetch_slots(token, user, state["pos_id"], exam_type, today.isoformat())
    wanted = [s for s in slots if today <= date.fromisoformat(s[0]) <= end_date]
    seen = {tuple(s) for s in state.get("seen", [])}
    new = [s for s in wanted if s not in seen]
    # Remember only slots still open, so a slot that is taken and freed again alerts again.
    state["seen"] = [list(s) for s in wanted]

    print(f"{datetime.now(TZ):%Y-%m-%d %H:%M} {state['pos_name']}: "
          f"{len(slots)} open, {len(wanted)} on or before {end_date}, {len(new)} new")
    if new:
        lines = [describe(*s) for s in new[:15]]
        if len(new) > 15:
            lines.append(f"...and {len(new) - 15} more")
        notify(
            f"{len(new)} new road test slot{'s' if len(new) > 1 else ''} at {state['pos_name']}",
            "\n".join(lines) + "\n\nTap to open ICBC booking.",
        )


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
            check_once(state)
            if state.get("error"):
                notify("ICBC checker working again", "Slot checks are succeeding again.",
                       priority="low", tags="white_check_mark")
                state["error"] = None
        except CheckError as e:
            failed = True
            print(f"ERROR: {e}", file=sys.stderr)
            # Alert once when it starts failing, not on every run.
            if not state.get("error"):
                try:
                    notify("ICBC checker failing", str(e), priority="default", tags="warning")
                except Exception as ne:
                    print(f"Could not send failure alert: {ne}", file=sys.stderr)
            state["error"] = str(e)
        save_state(state_file, state)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
