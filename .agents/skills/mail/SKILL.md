---
name: mail
description: Read Yandex HSE mailbox folders, message bodies and attachments without changing read flags.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/mail/mail.sh folders
scripts/mail/mail.sh sync --since YYYY-MM-DD --limit 100
scripts/mail/mail.sh attachment --mid MESSAGE_ID --hid PART_ID --name FILE_NAME
```

Uses optional Node/Playwright transport. Session login/import-state is documented in README. Do not load mailbox UI, send mail or mark read. Sync defaults to Inbox; inspect folders to find Sent or other folders. Attachments return base64, not persistent files.

All student state belongs in ignored data/. Never commit secrets or source content.
