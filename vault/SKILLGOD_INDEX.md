---
name: SkillGod Index
type: index
description: Use when browsing the full skill vault in Obsidian or reviewing vault health
updated: 2026-03-24
total_skills: 1944
---

# SkillGod Vault Index

> Auto-generated 2026-03-24 · 1944 skills across 10 categories

## By Category

| Category | Skills |
|---|---|
| [[coding]] | 572 |
| [[agents]] | 461 |
| [[design]] | 250 |
| [[writing]] | 168 |
| [[devops]] | 157 |
| [[research]] | 100 |
| [[security]] | 96 |
| [[api]] | 79 |
| [[instincts]] | 32 |
| [[react]] | 29 |

## All Skills (Dataview)

```dataview
TABLE description, confidence, source
FROM "vault"
WHERE type = "skill"
SORT confidence DESC
LIMIT 50
```

## Instincts (always-on)

```dataview
LIST description
FROM "vault/instincts"
WHERE type = "instinct"
```

## Top Agent Skills

```dataview
TABLE description, source
FROM "vault/agents"
SORT file.mtime DESC
LIMIT 20
```

## Recently Added

```dataview
TABLE description, confidence
FROM "vault"
SORT file.mtime DESC
LIMIT 10
```