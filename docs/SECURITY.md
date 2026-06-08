# Security Policy

## Security Scope

This beta release covers the local wechatDHA pipeline and Lens Advisor experience, including multimodal processing, Advisor APIs, frontend workflows, feedback capture, and roundtable sessions.

## Privacy-First Defaults

- Keep raw chat exports, private media, generated artifacts, model weights, audit logs, and local secrets out of Git.
- Store API keys only in `local_secrets/.env.advisor`.
- Use `configs/anonymization.yaml.template` and `configs/confirmed_names.yaml.template` as public examples.
- Keep real identity maps and confirmed private names in ignored local files only.
- Treat `测试用户A` and `测试用户B` as public test placeholders, not real user identities.

## Local Data Boundaries

The project is designed for local-first processing. User data should remain in ignored runtime directories unless the operator explicitly exports sanitized beta feedback.

Ignored sensitive paths include:

- `raw/`
- `artifacts/`
- `timeline_out/`
- `advisor_out/`
- `local_secrets/`
- model checkpoints and generated training outputs

## Reporting Security Issues

Do not open a public issue with secrets, raw chats, private screenshots, API keys, or identity mappings.

When reporting a security issue, include:

- A short description of the issue
- Reproduction steps
- Affected command, endpoint, or UI page
- Whether private data, API keys, or model artifacts may be exposed
- Sanitized logs or screenshots only

## Pre-Release Checklist

- No real PII appears in tracked files.
- No API keys appear in tracked files or Git history.
- Template files contain placeholders only.
- `.gitkeep` files are used only as safe directory skeleton placeholders.
- README and beta-facing docs describe local data boundaries.
- Tag and push are deferred until release-owner approval.

## Safety Boundaries

Lens Advisor and roundtable outputs are non-diagnostic support tools. They must not be presented as a replacement for professional medical, legal, or mental-health advice.

If crisis or self-harm risk is detected, the product should prioritize safety guidance and appropriate external support channels.
