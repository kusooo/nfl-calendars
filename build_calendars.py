#!/usr/bin/env python3
"""Build subscribable .ics calendars for NFL teams, the playoffs and prime-time games
from ESPN's public API, and post a recap (GitHub issue) after each of our teams' games.

Stdlib only. Run: python3 build_calendars.py [--season YYYY] [--out calendars]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
ET = ZoneInfo("America/New_York")
GAME_LENGTH = timedelta(hours=3, minutes=30)
REG_WEEKS = range(1, 19)
POST_WEEKS = (1, 2, 3, 5)  # postseason week 4 is the Pro Bowl; skip it
PRIME_TIME_HOUR_ET = 19
RECAP_WINDOW = timedelta(days=4)  # only recap games this recent (avoids backfilling old games)
ROOT = Path(__file__).parent
RECAP_STATE = ROOT / "recaps.json"

# file name -> (ESPN team id, short name)
TEAMS = {
    "eagles": ("21", "Eagles"),
    "texans": ("34", "Texans"),
}
TEAM_CALENDAR_NAMES = {"eagles": "Philadelphia Eagles", "texans": "Houston Texans"}

DIVISIONS = {
    "AFC East": "BUF MIA NE NYJ", "AFC North": "BAL CIN CLE PIT",
    "AFC South": "HOU IND JAX TEN", "AFC West": "DEN KC LAC LV",
    "NFC East": "DAL NYG PHI WSH", "NFC North": "CHI DET GB MIN",
    "NFC South": "ATL CAR NO TB", "NFC West": "ARI LAR SF SEA",
}
TEAM_DIVISION = {t: div for div, teams in DIVISIONS.items() for t in teams.split()}
# Well-known rivalries between teams in different divisions
RIVALRIES = {
    frozenset({"PHI", "PIT"}): "Battle of Pennsylvania",
    frozenset({"HOU", "DAL"}): "Governor's Cup (Battle of Texas)",
    frozenset({"NYG", "NYJ"}): "Battle of New York",
    frozenset({"LAR", "LAC"}): "Battle of Los Angeles",
    frozenset({"SF", "DAL"}): "49ers-Cowboys rivalry",
    frozenset({"SF", "GB"}): "49ers-Packers rivalry",
    frozenset({"KC", "BUF"}): "Chiefs-Bills rivalry",
    frozenset({"NE", "IND"}): "Patriots-Colts rivalry",
    frozenset({"BAL", "IND"}): "Ravens-Colts rivalry",
    frozenset({"MIA", "TB"}): "Battle of Florida",
}


def current_season(today=None):
    """NFL season year: the season that runs Sept YYYY - Feb YYYY+1. Rolls over in March."""
    today = today or date.today()
    return today.year if today.month >= 3 else today.year - 1


def fetch(url, retries=3, data=None, headers=None, method=None):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method,
                                         headers={"User-Agent": "nfl-calendars/1.0", **(headers or {})})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise RuntimeError(f"failed to fetch {url}: {e}") from e
            time.sleep(2 * (attempt + 1))


# ---------- data loading ----------

class Season:
    """All league games for one season, plus the regular-season week calendar."""

    def __init__(self, year):
        self.year = year
        self.regular, self.post, self.week_dates = [], [], {}
        for week in REG_WEEKS:
            data = fetch(f"{API}/scoreboard?seasontype=2&week={week}&dates={year}")
            self.regular.extend(data.get("events", []))
            if week == 1:
                for cal in (data.get("leagues") or [{}])[0].get("calendar", []):
                    if str(cal.get("value")) == "2":
                        for entry in cal.get("entries", []):
                            self.week_dates[int(entry["value"])] = entry["startDate"]
        for week in POST_WEEKS:
            data = fetch(f"{API}/scoreboard?seasontype=3&week={week}&dates={year}")
            self.post.extend(data.get("events", []))


# ---------- game helpers ----------

def comp(ev):
    return ev["competitions"][0]


def side(ev, home_away):
    return next((c for c in comp(ev).get("competitors", []) if c.get("homeAway") == home_away), {})


def team_id(c):
    return str((c.get("team") or {}).get("id", ""))


def abbr(c):
    return (c.get("team") or {}).get("abbreviation") or "TBD"


def team_name(c, full=False):
    t = c.get("team") or {}
    return (t.get("displayName") if full else (t.get("shortDisplayName") or t.get("name"))) or "TBD"


def score(c):
    s = c.get("score")
    if isinstance(s, dict):
        s = s.get("displayValue")
    return int(float(s)) if s not in (None, "") else None


def completed(ev):
    return bool(((comp(ev).get("status") or ev.get("status") or {}).get("type") or {}).get("completed"))


def start_utc(ev):
    return datetime.strptime(ev["date"].replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)


def time_valid(ev):
    c = comp(ev)
    return bool(ev.get("timeValid", c.get("timeValid", True))) and not (c.get("status") or {}).get("isTBDFlex")


def involves(ev, tid):
    return any(team_id(c) == tid for c in comp(ev).get("competitors", []))


def is_international(ev):
    country = ((comp(ev).get("venue") or {}).get("address") or {}).get("country")
    return bool(country) and country != "USA"


def is_prime_time(ev):
    et = start_utc(ev).astimezone(ET)
    christmas = et.month == 12 and et.day == 25
    return time_valid(ev) and (et.hour >= PRIME_TIME_HOUR_ET or christmas) and not is_international(ev)


def round_name(ev):
    notes = comp(ev).get("notes") or []
    return notes[0].get("headline") if notes else None


def broadcasts(ev):
    names = []
    for b in comp(ev).get("broadcasts", []):
        if b.get("names"):
            names.extend(b["names"])
        elif (b.get("media") or {}).get("shortName"):
            names.append(b["media"]["shortName"])
    return ", ".join(dict.fromkeys(names))


def betting_line(ev):
    if completed(ev):
        return None
    odds = comp(ev).get("odds") or []
    if not odds:
        return None
    o = odds[0]
    parts = [o["details"]] if o.get("details") else []
    if o.get("overUnder") is not None:
        parts.append(f"O/U {o['overUnder']:g}")
    return ", ".join(parts) or None


def kickoff_text(ev):
    et = start_utc(ev).astimezone(ET)
    day = et.strftime("%a %b ") + str(et.day)
    return f"{day}, {et.strftime('%I:%M %p').lstrip('0')} ET" if time_valid(ev) else f"{day} (time TBD)"


# ---------- records ----------

def fmt_record(r):
    w, l, t = r
    return f"{w}-{l}-{t}" if t else f"{w}-{l}"


def compute_records(regular_games):
    """Return (current records by team id, record of each team right after each game by (event id, team id))."""
    current, after = {}, {}
    for ev in sorted(regular_games, key=lambda e: e["date"]):
        if not completed(ev):
            continue
        home, away = side(ev, "home"), side(ev, "away")
        hs, as_ = score(home), score(away)
        if hs is None or as_ is None:
            continue
        for me, my, their in ((home, hs, as_), (away, as_, hs)):
            r = current.setdefault(team_id(me), [0, 0, 0])
            r[0 if my > their else 1 if my < their else 2] += 1
            after[(ev["id"], team_id(me))] = tuple(r)
    return {k: tuple(v) for k, v in current.items()}, after


# ---------- ICS ----------

def _escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """Fold lines to 75 octets per RFC 5545."""
    if len(line.encode("utf-8")) <= 75:
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


def _stamp(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


def vevent(uid, start, summary, description, location=None, all_day_date=None):
    # Fixed DTSTAMP keeps files byte-identical between runs unless the game data changes.
    lines = ["BEGIN:VEVENT", f"UID:{uid}@nfl-calendars", "DTSTAMP:" + _stamp(start)]
    if all_day_date:
        lines.append("DTSTART;VALUE=DATE:" + all_day_date.strftime("%Y%m%d"))
        lines.append("DTEND;VALUE=DATE:" + (all_day_date + timedelta(days=1)).strftime("%Y%m%d"))
    else:
        lines.append("DTSTART:" + _stamp(start))
        lines.append("DTEND:" + _stamp(start + GAME_LENGTH))
    lines.append("SUMMARY:" + _escape(summary))
    lines.append("DESCRIPTION:" + _escape(description))
    if location:
        lines.append("LOCATION:" + _escape(location))
    lines.append("END:VEVENT")
    return lines


def matchup_note(a, b):
    notes = []
    div = TEAM_DIVISION.get(a)
    if div and div == TEAM_DIVISION.get(b):
        notes.append(f"Division game ({div})")
    if frozenset({a, b}) in RIVALRIES:
        notes.append(f"Rivalry: {RIVALRIES[frozenset({a, b})]}")
    return " | ".join(notes) or None


def game_vevent(ev, records, recap=None):
    """records: current records for this game's season (used for upcoming games)."""
    home, away = side(ev, "home"), side(ev, "away")
    post = (ev.get("season") or {}).get("type") == 3
    rnd = round_name(ev)

    if completed(ev):
        title = f"{abbr(away)} {score(away)} @ {abbr(home)} {score(home)} (Final)"
    else:
        title = f"{abbr(away)} @ {abbr(home)}"
    if post and rnd:
        title = f"{rnd}: {title}"
    if not time_valid(ev):
        title += " (time TBD)"

    desc = []
    if recap:
        desc += [recap, ""]
    desc.append(ev.get("name") or title)
    week = (ev.get("week") or {}).get("number")
    desc.append(rnd if post and rnd else f"Week {week}" if week else "")
    if not post and rnd:
        desc.append(rnd)  # e.g. flex-scheduling notes
    matchup = matchup_note(abbr(away), abbr(home))
    if matchup:
        desc.append(matchup)
    if broadcasts(ev):
        desc.append(f"TV: {broadcasts(ev)}")
    if betting_line(ev):
        desc.append(f"Line: {betting_line(ev)}")
    if not completed(ev):
        recs = [f"{abbr(c)} {fmt_record(records[team_id(c)])}" for c in (away, home) if team_id(c) in records]
        if recs:
            desc.append("Records: " + ", ".join(recs))
    if not time_valid(ev):
        desc.append("Kickoff time TBD")

    venue = comp(ev).get("venue") or {}
    addr = venue.get("address") or {}
    location = ", ".join(x for x in (venue.get("fullName"), addr.get("city"), addr.get("state") or addr.get("country")) if x)
    start = start_utc(ev)
    return vevent(f"espn-{ev['id']}", start, title, "\n".join(d for d in desc if d is not None),
                  location, None if time_valid(ev) else start.astimezone(ET).date())


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
    for _, ev_lines in sorted(events, key=lambda x: x[0]):
        lines.extend(ev_lines)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


# ---------- team calendars, byes and recaps ----------

def dedupe(events):
    return list({e["id"]: e for e in events}.values())


def recap_text(ev, tid, short, team_games, after):
    """Final score, result, record and next opponent for one of our team's completed games."""
    me = next(c for c in comp(ev)["competitors"] if team_id(c) == tid)
    opp = next(c for c in comp(ev)["competitors"] if team_id(c) != tid)
    mine, theirs = score(me), score(opp)
    result = "W" if mine > theirs else "L" if mine < theirs else "T"
    post = (ev.get("season") or {}).get("type") == 3

    lines = [f"Final: {team_name(me)} {mine}, {team_name(opp)} {theirs} ({result})"]
    rec = after.get((ev["id"], tid))
    if post:
        lines.append(f"{short} advance" if result == "W" else f"{short} season over")
    elif rec:
        lines.append(f"{short} record: {fmt_record(rec)}")

    later = [g for g in team_games if g["date"] > ev["date"]]
    if later:
        nxt = later[0]
        n_opp = next((c for c in comp(nxt)["competitors"] if team_id(c) != tid), {})
        where = "vs" if next(c for c in comp(nxt)["competitors"] if team_id(c) == tid).get("homeAway") == "home" else "@"
        bye = ""
        this_week, next_week = (ev.get("week") or {}).get("number"), (nxt.get("week") or {}).get("number")
        if not post and (nxt.get("season") or {}).get("type") == 2 and this_week and next_week and next_week - this_week > 1:
            bye = "Bye week, then "
        tv = f" ({broadcasts(nxt)})" if broadcasts(nxt) else ""
        lines.append(f"Next: {bye}{where} {team_name(n_opp, full=True)}, {kickoff_text(nxt)}{tv}")
    elif result != "L" or not post:
        lines.append("Next: not scheduled yet")
    return "\n".join(lines), f"{lines[0]}" + (f" | {lines[1]}" if len(lines) > 1 else "")


def bye_vevents(season, tid, short, games):
    played = {(g.get("week") or {}).get("number") for g in games if (g.get("season") or {}).get("type") == 2}
    out = []
    for week in REG_WEEKS:
        if week in played or week not in season.week_dates:
            continue
        week_start = datetime.strptime(season.week_dates[week].replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        sunday = week_start.astimezone(ET).date()
        sunday += timedelta(days=(6 - sunday.weekday()) % 7)
        start = datetime.combine(sunday, datetime.min.time(), tzinfo=timezone.utc)
        out.append((start.strftime("%Y-%m-%dT%H:%M"),
                    vevent(f"bye-{season.year}-w{week}-{tid}", start, f"{short} bye (Week {week})",
                           f"{short} have no game in Week {week}.", all_day_date=sunday)))
    return out


def post_recap_issues(recaps):
    """Open (and immediately close) a GitHub issue per new recap so GitHub notifies the repo owner."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    state = json.loads(RECAP_STATE.read_text()) if RECAP_STATE.exists() else []
    new = [r for r in recaps if r["key"] not in state]
    if not new:
        return
    if not (token and repo):
        print(f"{len(new)} recap(s) pending; set GITHUB_TOKEN and GITHUB_REPOSITORY to post them")
        return
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}
    for r in new:
        issue = fetch(f"https://api.github.com/repos/{repo}/issues", retries=2, headers=headers,
                      data=json.dumps({"title": r["title"], "body": r["body"]}).encode())
        fetch(issue["url"], retries=2, headers=headers, method="PATCH",
              data=json.dumps({"state": "closed", "state_reason": "completed"}).encode())
        state.append(r["key"])
        print(f"posted recap: {r['title']}")
    RECAP_STATE.write_text(json.dumps(state[-300:], indent=0) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--season", type=int, default=current_season())
    p.add_argument("--out", default=str(ROOT / "calendars"))
    p.add_argument("--no-recaps", action="store_true", help="don't post recap issues")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Include the previous season too, so games don't vanish between the March
    # rollover and the schedule release in May.
    seasons = [Season(args.season - 1), Season(args.season)]
    records = {}
    for s in seasons:
        records[s.year] = compute_records(s.regular)

    def season_of(ev):
        return (ev.get("season") or {}).get("year")

    def entry(ev, recap=None):
        current = records.get(season_of(ev), ({}, {}))[0]
        return (ev["date"], game_vevent(ev, current, recap))

    def write(name, filename, entries):
        (out / filename).write_bytes(build_ics(name, entries).encode("utf-8"))
        print(f"{filename}: {len(entries)} events")

    # Our teams' games live on their team calendars only, so they don't show twice.
    def ours(ev):
        return any(involves(ev, tid) for tid, _ in TEAMS.values())

    playoffs = dedupe(e for s in seasons for e in s.post if not ours(e))
    write("NFL Playoffs", "playoffs.ics", [entry(e) for e in playoffs])

    prime = dedupe(e for s in seasons for e in s.regular if is_prime_time(e) and not ours(e))
    write("NFL Prime Time", "primetime.ics", [entry(e) for e in prime])

    now = datetime.now(timezone.utc)
    recaps = []
    for slug, (tid, short) in TEAMS.items():
        entries = []
        for s in seasons:
            games = sorted(dedupe(e for e in s.regular + s.post if involves(e, tid)), key=lambda e: e["date"])
            if not any((g.get("season") or {}).get("type") == 2 for g in games):
                print(f"note: no {s.year} regular-season games for {short} yet", file=sys.stderr)
                continue
            after = records[s.year][1]
            for g in games:
                recap = None
                if completed(g):
                    recap, title = recap_text(g, tid, short, games, after)
                    if now - start_utc(g) <= RECAP_WINDOW:
                        recaps.append({"key": f"{g['id']}-{tid}", "title": title, "body": recap})
                entries.append(entry(g, recap))
            entries += bye_vevents(s, tid, short, games)
        write(TEAM_CALENDAR_NAMES[slug], f"{slug}.ics", entries)

    if not args.no_recaps:
        post_recap_issues(recaps)


if __name__ == "__main__":
    main()
