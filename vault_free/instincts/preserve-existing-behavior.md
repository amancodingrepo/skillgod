---
name: Preserve existing behavior unless changing it is the goal
type: instinct
tags: [quality, safety, regression]
triggers: [edit, modify, refactor, change, update]
description: Use when editing code that already works
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
When editing working code, preserve its existing behavior unless changing that behavior is the explicit task. If a change alters behavior as a side effect, call it out explicitly. Silent behavior changes are how one small fix quietly breaks something that used to work.
