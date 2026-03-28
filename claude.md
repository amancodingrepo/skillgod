# SkillGod — Agent Operating System

## What this is

SkillGod is not a skill collection. It is a **runtime** that combines three pillars —
memory, skills, and multi-agent orchestration — into one CLI tool that works with any
AI coding agent and any model. The vault is the product. The runtime is the moat.

One-liner: **"Claude knows how to code. SkillGod knows how YOU code."**

---

## Three pillars — where each repo contributes

### Pillar 1 — Memory (persistent context across sessions)
Sourced from: `claude-mem`, `everything-claude-code`, `ralph`

| Repo | What we take |
|------|-------------|
| `claude-mem` | SQLite schema, 5-hook lifecycle, worker daemon, RAD memory pattern |
| `everything-claude-code` | Instincts concept, confidence scoring, continuous learning v2 |
| `ralph` | Autonomous loop — run until task is genuinely done, not just once |

Memory stores: decisions, patterns, errors, context — per project.
Injected at: SessionStart (always), PreToolUse (relevant items only).
Never mutates the vault. Memory is a separate layer.

### Pillar 2 — Skills (contextual knowledge injection)
Sourced from: `superpowers`, `anthropic/skills`, `vercel-labs/skills`,
`vercel-labs/agent-skills`, `everything-claude-code`, `ui-ux-pro-max-skill`

| Repo | What we take |
|------|-------------|
| `superpowers` | SKILL.md format, TDD skill writing, "Use when..." description standard |
| `anthropic/skills` | 17 official production skills, reference format, marketplace structure |
| `vercel-labs/skills` | Deployment patterns, npx skills tooling |
| `vercel-labs/agent-skills` | Agent-specific skill patterns |
| `ui-ux-pro-max-skill` | Deep design intelligence — UI/UX specialist skill |
| `everything-claude-code` | Instincts layer, security scan patterns, skill stocktake |

Skills are: scored per task, injected at PreToolUse, encrypted in paid vault.
Three types: `instinct` (always-on), `skill` (scored), `doc-skill` (fetches live docs).

### Pillar 3 — Agents (multi-agent orchestration)
Sourced from: `ruflo`, `agency-agents`, `MiroFish`, `awesome-claude-code`, `ralph`

| Repo | What we take |
|------|-------------|
| `ruflo` | Swarm architecture, 259 MCP tools, hive-mind spawning, semantic routing |
| `agency-agents` | Specialist agent roster — frontend, backend, marketing, content |
| `MiroFish` | Visual agent patterns, diagram generation agents |
| `awesome-claude-code` | Hook catalog, slash-command patterns, agent orchestrators |
| `ralph` | Autonomous loop until PRD complete, exit detection, circuit breaker |

Key insight: each spawned agent gets its OWN skill injection based on its task type.
Frontend agent gets UI skills. Backend agent gets API skills. Nobody else does this.

### Ingestion layer — how sources become vault
Sourced from: `Skill_Seekers`, `VoltAgent/awesome-agent-skills`,
`hesreallyhim/awesome-claude-code`

| Repo | What we take |
|------|-------------|
| `Skill_Seekers` | URL/repo/PDF → normalised SKILL.md converter |
| `VoltAgent/awesome-agent-skills` | Catalog of 1234+ external skill links to ingest |
| `hesreallyhim/awesome-claude-code` | Curated hooks, commands, skill discovery |

---

## Project structure

```
skillgod/
├── CLAUDE.md                     ← you are here
├── sources/                      ← all cloned repos, READ ONLY never edit
│   ├── claude-mem/
│   ├── ruflo/
│   ├── superpowers/
│   ├── anthropic-skills/
│   ├── anthropic-native/
│   ├── everything-claude-code/
│   ├── vercel-skills/
│   ├── vercel-agent-skills/
│   ├── agency-agents/
│   ├── awesome-claude-code/
│   ├── skill-seekers/
│   ├── voltagent-skills/
│   ├── ralph/
│   ├── mirofish/
│   └── ui-ux-pro-max/
│
├── engine/                       ← Python — the brain
│   ├── ingest.py                 ← sources → vault normaliser (Skill_Seekers pattern)
│   ├── memory.py                 ← SQLite memory layer (claude-mem architecture)
│   ├── skills.py                 ← scoring + injection (superpowers format)
│   ├── agents.py                 ← spawning + routing (ruflo architecture)
│   ├── runtime.py                ← combines all three pillars
│   ├── mcp_server.py             ← FastMCP local server :3333
│   └── security.py               ← injection detection (everything-cc patterns)
│
├── vault/                        ← normalised skills — THE PRODUCT
│   ├── instincts/                ← always-on rules, ~20 files, never scored
│   ├── coding/                   ← python, js, ts, debugging, review
│   ├── design/                   ← ui-ux-pro-max skills, figma, layout
│   ├── writing/                  ← docs, readme, blog, comms
│   ├── devops/                   ← deploy, docker, ci/cd, terraform
│   ├── security/                 ← audit, scan, owasp, injection
│   ├── research/                 ← search, analyse, summarise
│   ├── agents/                   ← specialist agent skill sets
│   └── meta/                     ← auto-learned, needs review before promotion
│
├── db/
│   └── skillgod.db               ← SQLite: skills index + memory + sessions
│
├── hooks/                        ← Claude Code + Antigravity lifecycle hooks
│   ├── session_start.py          ← loads instincts + memory (claude-mem pattern)
│   ├── pre_tool.py               ← security scan + skill injection
│   └── post_tool.py              ← captures memory + learns skills async
│
└── cli/
    └── main.go                   ← Go binary: sg run/find/learn/sync/build
```

---

## Skill format — the only format we use

```markdown
---
name: Descriptive skill name
type: skill
tags: [tag1, tag2, tag3, tag4]
triggers: [word1, word2, word3, word4]
description: Use when [specific triggering conditions — NOT a summary]
confidence: 0.85
source: anthropic
created: 2024-01-15
uses: 0
---

## Overview
One sentence.

## Steps
1. First step
2. Second step

## Examples
\`\`\`language
concrete example
\`\`\`
```

**CRITICAL — the one rule that makes discovery work (from obra/superpowers):**

`description` = triggering conditions ONLY. Never summarise the skill.

| Wrong | Right |
|-------|-------|
| `Systematic approach to debugging Python errors` | `Use when a Python script throws errors or behaves unexpectedly` |
| `Helps with React component architecture` | `Use when building or refactoring React components` |
| `A skill for code review` | `Use when reviewing a pull request or diff before merging` |

If description summarises the skill, Claude reads the description instead of the full
skill body and follows a summary instead of the actual methodology. This breaks everything.

---

## Skill types

**`instinct`** — always injected, no scoring, every single prompt.
- Body max 80 words
- Contains absolute language: always, never, must, every time
- Example: "Always verify output matches request before saying done"
- Lives in: `vault/instincts/`
- Source: `everything-claude-code` instincts pattern

**`skill`** — scored against task, injected when score ≥ 0.18, max 3 injected.
- Full methodology: overview + numbered steps + examples
- Has 4-6 specific trigger words
- Lives in: `vault/coding/`, `vault/design/` etc
- Source: `superpowers` + `anthropic/skills` format

**`doc-skill`** — fetches live library docs via Context7.
- Has `lib_id: /owner/repo` frontmatter field
- Fires when a known library name appears in task text
- Example: `lib_id: /facebook/react`

---

## Scoring engine

```
score = 0.0

for trigger in skill.triggers:
    if trigger in task_lower:          score += 0.35
    elif fuzzy_match(trigger) > 0.82:  score += 0.15

for tag in skill.tags:
    if tag in task_lower:              score += 0.20
    elif tag in task_words:            score += 0.08

word_overlap(description, task)        score += up to 0.25

score *= (0.7 + 0.3 * confidence)     # confidence multiplier
score += min(uses * 0.008, 0.04)      # frequency boost

→ inject top 3 skills scoring >= 0.18
→ inject ALL instincts regardless of score
```

---

## Memory architecture (claude-mem schema)

Five lifecycle hooks:

| Hook | Fires | Does |
|------|-------|------|
| `SessionStart` | IDE opens | Load instincts + recent project memory |
| `UserPromptSubmit` | User types | Security scan |
| `PreToolUse` | Before Claude acts | Score skills + attach relevant memory |
| `PostToolUse` | After Claude responds | Capture decisions + maybe learn skill |
| `SessionEnd` | IDE closes | Summarise session → SQLite |

SQLite tables (from claude-mem):
- `skills` — vault index, scores, usage counts
- `memory` — decisions/patterns/errors per project
- `sessions` — session metadata and summaries

Memory kinds: `decision`, `pattern`, `error`, `context`

---

## Agent orchestration (ruflo + agency-agents)

When task complexity warrants it, runtime decomposes and spawns specialists.
Per-agent skill injection is our unique capability — nobody else does this.

```
user task → decompose → specialist agents, each with own skills

"build landing page with contact form"
  → frontend agent   [ui-ux skills + react skills + css skills]
  → backend agent    [api skills + validation + email handling]
  → test agent       [playwright + accessibility + performance]

results → aggregate → memory capture
```

Specialist agents available (from agency-agents):
`frontend`, `backend`, `devops`, `security-auditor`,
`code-reviewer`, `docs-writer`, `test-engineer`,
`marketing`, `content`, `research`

Each agent profile lives in `vault/agents/` as a skill file.

---

## Security (from everything-claude-code / AgentShield)

Scans every input before processing. Blocked patterns:

```
ignore (all|previous|above) (instructions|rules)
you are now [different AI]
act as (unrestricted|jailbroken|DAN)
<|im_start|> / <|im_end|>
disregard your (training|guidelines)
forget your instructions
new persona / DAN mode
```

Blocked → logged → returned with warning → never processed.
Never disable this. It protects the product and the user.

---

## Build order — do not skip steps

```
Step 1: engine/ingest.py        parse all sources → vault
Step 2: engine/memory.py        SQLite schema + CRUD
Step 3: engine/skills.py        scoring engine + injector
Step 4: engine/security.py      injection scanner
Step 5: engine/agents.py        spawning + per-agent skill routing
Step 6: engine/runtime.py       SkillGodRuntime class combining 1-5
Step 7: engine/mcp_server.py    FastMCP — exposes runtime as tools
Step 8: hooks/                  Claude Code PreToolUse / PostToolUse / SessionStart
Step 9: cli/main.go             Go binary wrapping Python engine
```

---

## MCP tools (what Claude Code and Antigravity connect to)

```
find_skills(task)              → scored skill list
inject_context(task)           → augmented prompt string
save_memory(summary, kind)     → void
get_memory(project, limit)     → memory list
learn_skill(task, output)      → Skill | None
stocktake()                    → vault health report
spawn_agents(task)             → list of agent results
security_scan(text)            → threat list
vault_stats()                  → counts and top skills
sync_vault(license_key)        → skills downloaded
```

---

## Confidence levels

| Range | Meaning | Location |
|-------|---------|----------|
| 0.90–0.95 | Official / production-tested | `vault/coding/` promoted |
| 0.80–0.89 | Community validated | `vault/*/` normal |
| 0.70–0.79 | Ingested, needs real-world use | `vault/*/` use with caution |
| 0.50–0.69 | Auto-learned, unreviewed | `vault/meta/` review before use |
| < 0.50 | Discard — do not ingest | Never written to vault |

---

## Monetisation

```
Free:  runtime (open source) + 30 starter skills + skill builder
Pro:   $15/mo — full vault 200+ skills + monthly updates + enhancer
Team:  $20/seat — shared team vault + admin + analytics
```

Licensing: LemonSqueezy (0 monthly cost, 5% per transaction).
Vault encryption: AES-256, license key + machine ID = decrypt key.
Offline grace: 30 days — never break a dev's workflow.

---

## Working rules for this project

- `sources/` is read-only. Never edit files there.
- Every new skill must pass: description starts with "Use when"
- Every new skill must pass: `python engine/skillgod_v2.py stocktake`
- Auto-learned skills start in `vault/meta/` at confidence ≤ 0.69
- Promote to category vault only after human review
- Security scanner runs on ALL input — never bypass or disable
- Memory layer never touches vault — separate concerns always
- Per-agent skill injection is a feature — preserve it in all refactors
- The vault is production code — treat every skill file with that seriousness