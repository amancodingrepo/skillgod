---
name: Never mutate the vault directly
type: instinct
tags: [vault, safety, architecture]
triggers: [edit, modify, change, update, delete]
description: Use when any action might touch files in vault/ or sources/
confidence: 0.99
source: skillgod-core
created: 2024-01-01
uses: 0
---
Never directly edit files in vault/ or sources/ during a session.
Vault changes go through engine/ingest.py or sg learn only.
sources/ is read-only forever. Memory changes go through memory.py only.
