# SkillGod

**Claude knows how to code. SkillGod knows how *you* code.**

SkillGod is a runtime that sits between you and your AI coding tool. Before every response, it injects the right skills, your project memory, and routes complex tasks to specialist agents — automatically.

No prompt engineering. No copy-pasting context. It just works.

---

## The problem

Claude is brilliant out of the box. But it doesn't know:
- Your team's debugging methodology
- Which deployment pattern your project uses
- What you decided last Tuesday about state management
- That the last time it suggested Redux, you reworked it three times

Every session starts cold. SkillGod fixes that.

---

## What changes

| | Without SkillGod | With SkillGod |
|---|---|---|
| Context per prompt | 0 | 3 scored skills + 32 instincts |
| Memory across sessions | Cold start every time | SQLite per project |
| Agent routing | One model, one task | 10 specialist agents, each with own skills |
| Vault | — | 1,944 skills |
| Learns from your feedback | No | Yes (accept/rework signals) |
| Prompt injection protection | No | Yes (security scan on every input) |

---

## How it works

```
Your prompt
    │
    ▼
┌──────────────────────────────────────────────┐
│  Security scan — block injections first      │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  Pillar 1 — Skills                           │
│  Score 1,944 skills against your task        │
│  Inject top 3 + all 32 instincts             │
│  (instincts fire every single prompt)        │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  Pillar 2 — Memory                           │
│  Load decisions, patterns, errors            │
│  for this specific project                   │
│  Record accept/rework signals after          │
└──────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  Pillar 3 — Agents (complex tasks only)      │
│  Decompose → spawn specialists               │
│  Frontend agent gets UI skills               │
│  Backend agent gets API skills               │
│  Nobody else does this                       │
└──────────────────────────────────────────────┘
    │
    ▼
Claude (or any AI tool)
```

---

## Install

```bash
# macOS (Apple Silicon)
curl -L https://skillgod.dev/dist/sg-mac-arm64 -o /usr/local/bin/sg && chmod +x /usr/local/bin/sg

# macOS (Intel)
curl -L https://skillgod.dev/dist/sg-mac-intel -o /usr/local/bin/sg && chmod +x /usr/local/bin/sg

# Linux
curl -L https://skillgod.dev/dist/sg-linux -o /usr/local/bin/sg && chmod +x /usr/local/bin/sg

# Windows (PowerShell)
irm https://skillgod.dev/install.ps1 | iex

# From source
git clone https://github.com/skillgod/skillgod
cd skillgod
pip install -r requirements.txt
python engine/ingest.py
sg init
```

**Then restart Claude Code.** Skills inject automatically via MCP — no other config needed.

---

## Quick start

```bash
sg init                          # detects IDE, writes .mcp.json, rebuilds index
sg find "debug python traceback" # test skill discovery
sg stats                         # vault counts and health
sg scan "your prompt here"       # test security scanner
```

---

## The vault

**1,944 skills** across 11 categories. Every skill has:
- Trigger words for accurate scoring
- A description that starts with "Use when..." (not a summary — this is what makes discovery work)
- Confidence score (0.65–0.95)
- Source attribution

| Category | Skills | What's in it |
|----------|--------|--------------|
| coding | 572 | debugging, TDD, Python, Go, Rust, review patterns |
| agents | 461 | frontend, backend, devops, security, docs specialists |
| design | 250 | UI/UX pro, brand, design systems, Figma patterns |
| writing | 168 | technical docs, README, blog, comms |
| devops | 157 | Docker, Kubernetes, Terraform, CI/CD, cloud deploy |
| instincts | 32 | always-on rules — verify before done, security first |
| research | 100 | deep research, market analysis, summarisation |
| security | 96 | OWASP, audit, injection detection, threat modelling |
| api | 79 | REST, GraphQL, API design, SDK patterns |
| react | 29 | hooks, composition, React Native, Expo |
| meta | — | auto-learned skills pending review |

---

## Commands

```
sg init              Set up SkillGod — detects IDE, writes .mcp.json
sg find <task>       Score vault against a task, show top matches
sg stats             Vault health, category counts, index status
sg build             Interactive skill builder — guided prompts
sg learn             Save any output as a new skill (goes to meta/)
sg sync              Rebuild local index (free) or decrypt full vault (pro: sg sync --key YOUR-KEY)
sg scan <text>       Scan for prompt injection threats
sg signals           Accept/rework rates per skill — see what's working
sg promote           Review auto-learned skills, approve for vault promotion
sg run <tool>        Run any AI tool with SKILLGOD_ROOT injected
```

---

## MCP tools (what Claude Code calls directly)

Once `sg init` runs, these tools are available inside every Claude Code session:

```
find_skills(task)         → top scored skills for this task
inject_context(task)      → full augmented prompt string
save_memory(summary)      → persist a decision to project memory
get_memory(project)       → retrieve recent project context
learn_skill(task, output) → auto-generate skill from session output
stocktake()               → vault health report
spawn_agents(task)        → decompose and route to specialist agents
security_scan(text)       → threat detection
vault_stats()             → live vault counts
```

---

## Pricing

| Feature | Free | Early Adopter | Pro |
|---------|------|---------------|-----|
| **Price** | Free forever | **$7/mo locked forever** | $10/mo |
| **Who** | Everyone | First 200 users only | User 201+ |
| Skills | 30 starter skills | 885+ (full vault) | 885+ (full vault) |
| Instincts | All 32 | All 32 | All 32 |
| Memory | Full SQLite layer | Full SQLite layer | Full SQLite layer |
| Agent layer | Basic | Full multi-agent | Full multi-agent |
| Monthly vault updates | No | Yes | Yes |
| Skill enhancer + signal analytics | No | Yes | Yes |
| `sg sync --key` | No | Yes | Yes |

The free tier is not crippled — 30 skills, full memory, and the basic agent layer is enough to genuinely feel the difference.

**Early Adopter pricing is locked forever.** First 200 users pay $7/mo for life, no matter what the price does later.

**Referral program:**
- Get a referral link from any Pro user → sign up at **$7/mo locked forever**, even after the 200-user window closes
- Refer a friend who converts to paid → you get **1 free month** ($10 value) automatically

License via LemonSqueezy. Offline grace period: 30 days — your workflow never breaks.

---

## Why the vault is the moat

Anyone can build a skill injector. The vault is 1,944 curated, scored, and formatted skills that have been normalised from 12 source repos into a single consistent format. Every description starts with "Use when..." — not a summary — which is the detail that makes semantic scoring work.

The free runtime is open source. The vault is the product.

---

## Built on the shoulders of

SkillGod assembles the best patterns from 12 open-source repos:

| Repo | What we took |
|------|-------------|
| [obra/superpowers](https://github.com/obra/superpowers) | SKILL.md format, "Use when" description standard |
| [anthropics/skills](https://github.com/anthropics/skills) | 17 production skills, marketplace format |
| [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | SQLite memory schema, 5-hook lifecycle |
| [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) | Instincts layer, confidence scoring |
| [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) | 179 specialist agent profiles |
| [snarktank/ralph](https://github.com/snarktank/ralph) | Autonomous loop, circuit breaker pattern |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | Deep design intelligence — 161 palettes, 57 font pairings |
| [vercel-labs/skills](https://github.com/vercel-labs/skills) | Deployment patterns |
| [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | Agent-specific skill patterns |
| [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | Hook catalog, slash-command patterns |
| [yusufkaraaslan/Skill_Seekers](https://github.com/yusufkaraaslan/Skill_Seekers) | Ingestion pipeline design |
| [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) | Official team skills from Stripe, Cloudflare, Netlify, HuggingFace |

---

## Architecture

```
skillgod/
├── engine/
│   ├── ingest.py        ← sources → vault normaliser
│   ├── memory.py        ← SQLite memory layer
│   ├── skills.py        ← scoring + injection engine
│   ├── agents.py        ← spawning + per-agent skill routing
│   ├── runtime.py       ← combines all three pillars
│   ├── mcp_server.py    ← FastMCP server on :3333
│   ├── security.py      ← injection detection
│   ├── encryption.py    ← AES-256-GCM vault encryption
│   ├── signals.py       ← accept/rework tracking
│   └── variants.py      ← promotion queue
├── hooks/
│   ├── session_start.py ← loads instincts + memory
│   ├── pre_tool.py      ← security scan + skill injection
│   └── post_tool.py     ← captures memory + learns skills
├── vault/               ← 1,944 normalised skills (open)
├── cli/                 ← Go binary: sg
└── deploy/              ← Railway API stub (future backend)
```

---

MIT License. Vault content retains original licenses from source repos.
