---
name: smartpro
description: Read SmartPro account and explicitly identified applications/projects.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/smartpro/smartpro.sh user
scripts/smartpro/smartpro.sh participant PARTICIPANT_ID
scripts/smartpro/smartpro.sh project PROJECT_ID
```

Uses HSE SSO cookies from LMS login. IDs belong to the owner, never assume another student’s IDs. If needed, --select-student-role explicitly selects the sole existing student role as login state. Never apply, approve or submit.

All student state belongs in ignored data/. Never commit secrets or source content.
