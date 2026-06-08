# Beta User Guide

## Scope

This beta release focuses on the Lens Advisor experience, including chat analysis, safety-aware response generation, arena comparison, and multi-agent roundtable discussion.

## Before You Start

- Use a local Python environment named `wechatDHA`.
- Keep all private data under ignored runtime paths.
- Store API keys only in `local_secrets/.env.advisor`.
- Use template files in `configs/` as examples, then fill private values locally.

## Privacy Rules

Do not commit:

- Raw chat exports
- Real names or phone numbers
- API keys
- Model weights
- Generated training, analysis, index, or audit-log files

## Basic Workflow

1. Configure local secrets and templates.
2. Start the backend service.
3. Start the frontend dashboard.
4. Load sample data or your own local ignored data.
5. Report beta issues with reproduction steps and screenshots when possible.

## Feedback

When reporting feedback, include:

- Page or endpoint used
- Expected behavior
- Actual behavior
- Console or backend logs with private data removed
- Whether the issue is blocking, major, or minor
