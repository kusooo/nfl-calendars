# NFL calendars

Auto-updating `.ics` calendars built from ESPN's public schedule API:

| Calendar | File |
|---|---|
| Philadelphia Eagles (regular season + playoffs) | `calendars/eagles.ics` |
| Houston Texans (regular season + playoffs) | `calendars/texans.ics` |
| NFL Playoffs + Super Bowl | `calendars/playoffs.ics` |
| NFL Prime Time (Thu/Sun/Mon night + Christmas; no international games) | `calendars/primetime.ics` |

A GitHub Action rebuilds them daily: final scores go into event titles, flexed kickoff times update, playoff matchups fill in as they're set, and the season rolls over every March automatically. Each calendar keeps the previous season too, so nothing disappears between the rollover and the May schedule release. Games without a set kickoff show as all-day "time TBD" events.

What's in each event:
- **Titles** stay simple: `HOU @ TEN`. Descriptions add TV, division/rivalry notes, current records and the betting line once it's posted (about a week out).
- **Finished games:** the final score. On the team calendars, the description has a recap: result, record and next opponent.
- **Bye weeks:** an all-day "Eagles bye (Week 10)" event on the team calendars.

## Recap notifications

After each Eagles or Texans game, the workflow opens (and immediately closes) a GitHub issue with the recap, so GitHub notifies you. To get these by email or push, keep **Watch → All Activity** on the repo and turn on email/mobile under github.com/settings/notifications.

## Setup

1. Push this folder to a **public** GitHub repo.
2. On GitHub: **Actions → Update NFL calendars → Run workflow** (and enable Actions if prompted).

## Subscribe

Use these URLs:

```
https://raw.githubusercontent.com/kusooo/nfl-calendars/main/calendars/eagles.ics
https://raw.githubusercontent.com/kusooo/nfl-calendars/main/calendars/texans.ics
https://raw.githubusercontent.com/kusooo/nfl-calendars/main/calendars/playoffs.ics
https://raw.githubusercontent.com/kusooo/nfl-calendars/main/calendars/primetime.ics
```

- **Google Calendar:** Other calendars → **+** → From URL. (Google refreshes subscribed feeds every 12–24 h.)
- **Apple Calendar:** File → New Calendar Subscription. On iPhone: Settings → Calendar → Accounts → Add Subscribed Calendar.
- **Outlook:** Add calendar → Subscribe from web.

## Adding teams

Add entries to `TEAMS` and `TEAM_CALENDAR_NAMES` in `build_calendars.py` with the ESPN team id (found in `https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams`).
