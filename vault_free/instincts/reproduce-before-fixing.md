---
name: Reproduce a bug before fixing it
type: instinct
tags: [debugging, verification, quality]
triggers: [fix, bug, error, broken, repro]
description: Use when asked to fix a bug or unexpected behavior
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Reproduce a bug with a real failing case before attempting a fix; a fix for a bug you never reproduced is a guess. After changing code, re-run the exact reproduction, confirm it now passes, and check nothing else broke. Never claim a bug fixed on reasoning alone.
