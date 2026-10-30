## What and why
<!-- One or two sentences. Link the issue, for example: Fixes #123 -->

## Checks
- [ ] A test fails without this change and passes with it
- [ ] `pytest tests/pic` passes (backend); `npx tsc --noEmit` and `npx eslint` are clean (frontend)
- [ ] A database change has a migration (upgrade and downgrade tested), and existing data was checked against any new constraint
- [ ] No secrets, passwords or real customer data in the diff
- [ ] Controls still hold: tenant isolation, segregation of duties, an audit event for every state change
- [ ] Docs or runbook updated if behaviour changed
