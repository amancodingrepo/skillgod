---
name: Prefer small, reversible changes
type: instinct
tags: [quality, safety, process]
triggers: [change, rewrite, refactor, plan, migrate]
description: Use when planning how to make a change
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Prefer small, focused, reversible changes over large sweeping rewrites. Small diffs are easier to review, test, and roll back when something goes wrong. When a big change is unavoidable, stage it into smaller verifiable steps rather than one irreversible leap.
