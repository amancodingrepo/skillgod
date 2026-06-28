# Contributing to SkillGod

Thanks for contributing. The most valuable thing you can add is a well-written skill.

---

## Writing a skill

Every skill file is a `.md` file with YAML frontmatter. Copy this template:

```markdown
---
name: Descriptive skill name
type: skill
tags: [tag1, tag2, tag3, tag4]
triggers: [word1, word2, word3, word4]
description: Use when [specific triggering conditions]
confidence: 0.75
source: community
created: 2025-01-15
uses: 0
---

## Overview
One sentence describing what this skill does.

## Steps
1. First step
2. Second step
3. Third step

## Examples
\`\`\`language
concrete example here
\`\`\`
```

---

## The one rule that makes discovery work

**`description` = triggering conditions only. Never summarise the skill.**

| Wrong | Right |
|-------|-------|
| `Systematic approach to debugging Python errors` | `Use when a Python script throws errors or behaves unexpectedly` |
| `Helps with React component architecture` | `Use when building or refactoring React components` |
| `A skill for code review` | `Use when reviewing a pull request or diff before merging` |

If you write a summary instead of conditions, the scoring engine reads the description instead of the full skill body and follows a summary instead of your actual methodology. This breaks injection.

---

## Skill types

**`skill`** — standard, scored against each task, injected when score ≥ 0.18.
- Full methodology: overview + numbered steps + examples
- 4–6 specific trigger words

**`instinct`** — always injected, no scoring, fires on every prompt.
- Body max 80 words
- Absolute language: always, never, must, every time
- Reserved for critical rules only — use sparingly

---

## Confidence levels

| Range | Meaning |
|-------|---------|
| 0.90–0.95 | Official / production-tested |
| 0.80–0.89 | Community validated |
| 0.70–0.79 | Ingested, needs real-world use |

Set new community skills to `0.75`. Don't go above `0.85` unless it's been validated in production.

---

## Frontmatter fields

| Field | Required | Notes |
|-------|----------|-------|
| `name` | Yes | Title case, descriptive |
| `type` | Yes | `skill` or `instinct` |
| `tags` | Yes | 3–5 topic tags, lowercase |
| `triggers` | Yes | 4–6 exact words that appear in task text |
| `description` | Yes | Must start with `Use when` |
| `confidence` | Yes | 0.70–0.85 for new community skills |
| `source` | Yes | `community`, `anthropic`, or repo name |
| `created` | Yes | ISO date |
| `uses` | Yes | Set to `0` |

---

## Where skills live

```
vault_free/          ← 30 free skills (flat, no subdirs)
```

The full vault (1,944 skills) is in the Pro tier and not in this repo. Community contributions to `vault_free/` are welcome — open a PR adding your `.md` file directly to `vault_free/`.

---

## Submitting

1. Fork the repo
2. Add your skill file to `vault_free/your-skill-name.md`
3. Verify the description starts with `Use when`
4. Open a PR — title format: `skill: short description of what it covers`

PRs that fail the `Use when` check will be sent back. Everything else is welcome.
