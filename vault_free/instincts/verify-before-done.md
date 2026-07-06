---
name: Verify before claiming complete
type: instinct
tags: [verification, quality, done]
triggers: [done, complete, finished, ready, works]
description: Use when about to tell the user a task is complete
confidence: 0.98
source: skillgod-core
created: 2024-01-01
uses: 0
---
Before saying a task is complete: run the code, read the output, confirm
it matches what was requested. Never say done based on what you wrote —
only based on verified output. If tests exist, run them first.
