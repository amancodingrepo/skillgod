---
name: Confidence gate for vault promotion
type: instinct
tags: [vault, quality, confidence, promotion]
triggers: [promote, add, merge, publish, vault]
description: Use when considering adding a skill to the core vault
confidence: 0.98
source: skillgod-core
created: 2024-01-01
uses: 0
---
Auto-learned skills start in vault/meta/ at confidence <= 0.69.
Never promote to category vault without human review.
Never promote a skill whose description does not start with "Use when".
Never promote a skill with confidence < 0.70.
Run stocktake() before any promotion batch.
