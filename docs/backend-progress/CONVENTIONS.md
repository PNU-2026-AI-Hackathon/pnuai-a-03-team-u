# Backend Progress Rules

`docs/backend-progress/PROGRESS.md` is the backend status board. Update it whenever a backend PR changes implemented behavior, data flow, models, routes, deployment, or operational assumptions.

In addition, every vibe-coding session should leave a dated log file in this folder (`YYYY-MM-DD.md`, see `TEMPLATE.md`) recording what was implemented, fixed, blocked, and left undone in that session.

## When To Update

Update PROGRESS.md in the same PR when you:

- add, move, or remove backend folders or modules
- add or change DB models, migrations, or seed data
- add or change crawlers, parsers, normalizers, or external data sources
- add or change FastAPI routes, background jobs, or auth flows
- add environment variables or operational setup steps
- finish, defer, or invalidate an item listed under "아직 안 한 것" or "다음 후보 작업"

Do not update it for purely internal refactors that do not change how another teammate should use or continue the backend.

## Required Sections

Keep the README in this order:

1. Current date in the title.
2. Links to architecture/spec docs.
3. Current PR status table.
4. Implemented backend areas.
5. Usage examples only for flows that were actually tested.
6. DB models and migration status.
7. Environment variables.
8. Known gaps and next candidate tasks.

## Writing Rules

- Keep it factual and implementation-focused.
- Link to real files with relative Markdown links.
- Mark unverified work explicitly as `미검증` or `예정`.
- Do not include secrets, real passwords, tokens, or private student data.
- Do not paste large raw crawler outputs.
- If a PR has merged, update its status to `Merged`.
- If a file path changes, update every path reference in the README in the same PR.

## PR Checklist

Before opening a backend PR, check:

- Does this PR change backend behavior another teammate needs to know?
- Does `docs/backend-progress/README.md` still describe the current code?
- Are new env vars reflected in `backend/.env.example` and the README?
- Are incomplete pieces listed under known gaps instead of implied as done?
