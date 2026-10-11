#!/usr/bin/env python3
"""Build subscribable .ics calendars for NFL teams and the NFL playoffs from ESPN's public API.

Stdlib only. Run: python3 build_calendars.py [--season YYYY] [--out calendars]
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
ET = ZoneInfo("America/New_York")
GAME_LENGTH = timedelta(hours=3, minutes=30)
PRO_BOWL_WEEK = 4  # postseason week 4 is the Pro Bowl; skip it

# file name -> (ESPN team id, abbreviation, calendar name)
TEAMS = {
    "eagles": ("21", "PHI", "Philadelphia Eagles"),
    "texans": ("34", "HOU", "Houston Texans"),
}


def current_season(today=None):
    """NFL season year: the season that runs Sept YYYY - Feb YYYY+1. Rolls over in March."""
    today = today or date.today()
    return today.year if today.month >= 3 else today.year - 1


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nfl-calendars/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise RuntimeError(f"failed to fetch {url}: {e}") from e
            time.sleep(2 * (attempt + 1))


def team_regular_season(team_id, season):
    data = fetch(f"{API}/teams/{team_id}/schedule?season={season}&seasontype=2")
    return data.get("events", [])


def postseason_events(season):
    events = []
    for week in (1, 2, 3, 5):
        data = fetch(f"{API}/scoreboard?seasontype=3&week={week}&dates={season}")
        events.extend(data.get("events", []))
    return events


# ---------- event -> ICS ----------

def _escape(text):
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n"))


def _fold(line):
    """Fold lines to 75 octets per RFC 5545."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, chunk = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > (75 if not parts else 74):
            parts.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += b
    parts.append(chunk.decode("utf-8"))
    return "\r\n ".join(parts)


def _parse_utc(s):
    return datetime.strptime(s.replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)


def _score(c):
    s = c.get("score")
    if isinstance(s, dict):
        return s.get("displayValue")
    return s


def _abbr(c):
    return (c.get("team") or {}).get("abbreviation") or "TBD"


def event_lines(ev):
    comp = ev["competitions"][0]
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    status = (comp.get("status") or {}).get("type") or {}
    notes = comp.get("notes") or []
    round_name = notes[0].get("headline") if notes else None

    title = ev.get("shortName") or f"{_abbr(away)} @ {_abbr(home)}"
    if round_name:
        title = f"{round_name}: {title}"
    if status.get("completed"):
        title += f" (Final: {_abbr(away)} {_score(away)}, {_abbr(home)} {_score(home)})"

    desc = [ev.get("name", title)]
    week = ev.get("week")
    if isinstance(week, dict) and week.get("text"):
        desc.append(week["text"])
    tv = ", ".join(b["media"]["shortName"] for b in comp.get("broadcasts", []) if b.get("media", {}).get("shortName"))
    if tv:
        desc.append(f"TV: {tv}")
    time_valid = ev.get("timeValid", comp.get("timeValid", True)) and not (comp.get("status") or {}).get("isTBDFlex")
    if not time_valid:
        desc.append("Kickoff time TBD")

    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    location = ", ".join(x for x in (venue.get("fullName"), addr.get("city"), addr.get("state")) if x)

    start = _parse_utc(ev["date"])
    lines = ["BEGIN:VEVENT", f"UID:espn-{ev['id']}@nfl-calendars"]
    # Fixed DTSTAMP keeps files byte-identical between runs unless the game data changes.
    lines.append("DTSTAMP:" + start.strftime("%Y%m%dT%H%M%SZ"))
    if time_valid:
        lines.append("DTSTART:" + start.strftime("%Y%m%dT%H%M%SZ"))
        lines.append("DTEND:" + (start + GAME_LENGTH).strftime("%Y%m%dT%H%M%SZ"))
    else:
        day = start.astimezone(ET).date()
        lines.append("DTSTART;VALUE=DATE:" + day.strftime("%Y%m%d"))
        lines.append("DTEND;VALUE=DATE:" + (day + timedelta(days=1)).strftime("%Y%m%d"))
        title += " (time TBD)"
    lines.append("SUMMARY:" + _escape(title))
    lines.append("DESCRIPTION:" + _escape("\n".join(desc)))
    if location:
        lines.append("LOCATION:" + _escape(location))
    lines.append("END:VEVENT")
    return lines


def build_ics(name, events):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//nfl-calendars//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(name),
        "X-WR-TIMEZONE:America/New_York",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for ev in sorted(events, key=lambda e: (e["date"], e["id"])):
        lines.extend(event_lines(ev))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def involves(ev, team_id):
    return any(str((c.get("team") or {}).get("id")) == team_id for c in ev["competitions"][0].get("competitors", []))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, default=current_season())
    p.add_argument("--out", default=str(Path(__file__).parent / "calendars"))
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    playoffs = postseason_events(args.season)
    print(f"season {args.season}: {len(playoffs)} postseason games")
    (out / "playoffs.ics").write_bytes(build_ics(f"NFL Playoffs {args.season}", playoffs).encode("utf-8"))

    for slug, (team_id, _abbr_, name) in TEAMS.items():
        games = team_regular_season(team_id, args.season)
        if not games:
            print(f"warning: no regular-season games for {name}", file=sys.stderr)
        games += [e for e in playoffs if involves(e, team_id)]
        (out / f"{slug}.ics").write_bytes(build_ics(name, games).encode("utf-8"))
        print(f"{slug}: {len(games)} games")


if __name__ == "__main__":
    main()
