---
name: hse
description: Initialize AI Native HSE and diagnose source access before context gathering.
---

Read the repository AGENTS.md first. Run commands from the repository root.

```bash
scripts/hse/hse.sh init
scripts/hse/hse.sh status
scripts/doctor/doctor.sh
scripts/doctor/doctor.sh --online
```

This framework supplies access and navigation. Use source-specific skills for actual reads; no stored-content search exists. File presence is not session validity. Doctor clearly labels unprobed sources. Source output is transient; save final answers only when requested.

All student state belongs in ignored data/. Never commit secrets or source content.

Academic periods and Moscow timezone are automatic; manual config filling is not needed. Run scripts/hse/hse.sh period to inspect the current named module or gap-through-now selection. Calendar sources and coverage are described in README.
