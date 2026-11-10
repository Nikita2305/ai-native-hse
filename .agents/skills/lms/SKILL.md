---
name: lms
description: Read HSE Smart LMS course metadata, inline pages, contents and own grades.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/lms/lms.sh courses
scripts/lms/lms.sh page --course-id COURSE_ID
scripts/lms/lms.sh contents --course-id COURSE_ID
scripts/lms/lms.sh grades --course-id COURSE_ID
```

Login uses --secret-file with the owner’s credentials; see README. Check year and enrollment. Do not open arbitrary activity pages that might track completion. Inline page reading does not download all attachments.

All student state belongs in ignored data/. Never commit secrets or source content.

Login requires a private JSON file containing both username and password. A bare password is rejected; no mail address is inferred from config.
