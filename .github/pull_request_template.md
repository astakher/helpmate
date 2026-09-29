## What & why
<!-- One or two sentences. Link the issue: Closes #123 -->

## Workstream
- [ ] A — agent / LLM / memory / eval
- [ ] B — backend / data / integrations / security / deploy
- [ ] C — web app / voice / notifications

## Contract impact
- [ ] No change to `contracts/`, `domain/ports.py` or `api/schemas/`
- [ ] Additive change (new endpoint/field/event); I ran `scripts/export_openapi.py` and `npm run gen:api`
- [ ] Breaking change (discussed with all three members first)

## How I tested
<!-- Commands you ran, screenshots for UI changes, adapters used (fake/real) -->

## Checklist
- [ ] CI is green
- [ ] No secrets, personal data, audio or model files committed
- [ ] Agent-initiated writes still go through a proposal (no bypass of the approval flow)
