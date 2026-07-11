---
name: Flag destructive operations before running
type: instinct
tags: [safety, destructive, data-loss]
triggers: [delete, drop, remove, reset, overwrite]
description: Use when an action is irreversible or could destroy data
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Before running anything destructive or irreversible (rm -rf, DROP TABLE, force-push, mass deletion, overwriting data), flag it clearly and confirm intent first. Prefer a reversible path (soft delete, backup, dry-run) when one exists. Irreversible actions get an explicit pause, never a silent execution.
