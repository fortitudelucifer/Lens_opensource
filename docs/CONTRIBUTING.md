# Contributing to wechatDHA / Lens Advisor

Thank you for your interest in contributing to the wechatDHA and Lens Advisor beta.

## Ways to Contribute

### Report Issues

- Include the page, command, or endpoint involved.
- Provide exact reproduction steps.
- Include environment details.
- Remove private names, chat logs, API keys, screenshots with sensitive content, and generated runtime data before sharing logs.

### Suggest Features

- Describe the user scenario.
- Explain the expected behavior.
- Note whether the request affects privacy, safety, model routing, or local/cloud data boundaries.

### Submit Code

1. Create a feature branch.
2. Make focused changes with tests when possible.
3. Run relevant backend and frontend checks.
4. Open a pull request with a concise summary and verification notes.

## Development Setup

See `docs/QUICKSTART.md` for environment setup and local startup commands.

Use the `wechatDHA` conda environment for project scripts:

```bash
conda run -n wechatDHA python -m pytest tests
```

Frontend commands should be run from the `frontend/` package or with `--prefix frontend`.

## Privacy and Safety Rules

Do not commit:

- Raw chat exports
- Real names, phone numbers, IDs, addresses, or other PII
- API keys or local `.env` files
- Model weights or checkpoints
- Generated training, analysis, FAISS, audit-log, session, or report artifacts

Use templates and placeholders instead:

- `local_secrets/.env.advisor.example`
- `configs/anonymization.yaml.template`
- `configs/confirmed_names.yaml.template`
- `.gitkeep` files for ignored runtime directories

## Commit Message Types

Use concise conventional-style subjects:

- `feat`: new feature
- `fix`: bug fix
- `docs`: documentation update
- `test`: tests
- `chore`: tooling, cleanup, or repository maintenance
- `refactor`: internal restructuring without behavior changes

## Pull Request Checklist

Before submitting, confirm:

- No PII or real API keys are present in the diff.
- New user-facing behavior has documentation or release notes when appropriate.
- Relevant backend/frontend tests were run or explicitly deferred.
- Runtime outputs remain ignored by Git.

## License

By contributing, you agree that your contributions are provided under the repository license.
