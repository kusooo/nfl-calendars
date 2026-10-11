# NFL calendars

Auto-updating `.ics` calendars built from ESPN's public schedule API:

| Calendar | File |
|---|---|
| Philadelphia Eagles (regular season + playoffs) | `calendars/eagles.ics` |
| Houston Texans (regular season + playoffs) | `calendars/texans.ics` |
| NFL Playoffs + Super Bowl | `calendars/playoffs.ics` |

A GitHub Action rebuilds them daily: final scores go into event titles, flexed kickoff times update, playoff matchups fill in as they're set, and the season rolls over every March automatically. Each calendar keeps the previous season too, so nothing disappears between the rollover and the May schedule release. Games without a set kickoff show as all-day "time TBD" events.

## Setup

1. Create an empty **public** repo named `nfl-calendars` on GitHub, then from this folder:
   ```bash
   git init -b main && git add . && git commit -m "NFL calendars"
   git remote add origin https://github.com/kusooo/nfl-calendars.git
   git push -u origin main
   ```
2. On GitHub: **Actions → Update NFL calendars → Run workflow** (and enable Actions if prompted).

## Subscribe

Use these URLs:

```
https://raw.githubusercontent.com/kusooo/nfl-calendars/main/calendars/eagles.ics
https://raw.githubusercontent.com/kusooo/nfl-calendars/main/calendars/texans.ics
https://raw.githubusercontent.com/kusooo/nfl-calendars/main/calendars/playoffs.ics
```

- **Google Calendar:** Other calendars → **+** → From URL. (Google refreshes subscribed feeds every 12–24 h.)
- **Apple Calendar:** File → New Calendar Subscription. On iPhone: Settings → Calendar → Accounts → Add Subscribed Calendar.
- **Outlook:** Add calendar → Subscribe from web.

## Adding teams

Add an entry to `TEAMS` in `build_calendars.py` with the ESPN team id (found in `https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams`).
