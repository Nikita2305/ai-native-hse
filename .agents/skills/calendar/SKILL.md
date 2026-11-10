---
name: calendar
description: Read personal HSE ELK timetable and academic profile.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/calendar/calendar.sh sync --since YYYY-MM-DD --until YYYY-MM-DD
scripts/calendar/calendar.sh profile
```

Uses shared browser session. Timetable lessons do not prove assignment deadlines. Moodle calendar is available via lms calendar. A refresh-session may refresh authentication only.

All student state belongs in ignored data/. Never commit secrets or source content.

Default login is headless: login --secret-file PATH reads explicit {username,password} from a private JSON file and reuses HSE SSO cookies. login without credentials tries existing sessions. No browser window or session transfer is normally needed. Use --interactive only when the service requires MFA/manual authentication; never print credential contents.
