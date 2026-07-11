---
name: Don't over-abstract a one-off
type: instinct
tags: [quality, simplicity, design]
triggers: [abstract, generalize, framework, refactor, pattern]
description: Use when tempted to add layers, generalization, or a framework
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Don't build abstraction a task doesn't need. A one-off doesn't need a framework, a plugin system, or three layers of indirection. Solve the actual problem simply; generalize only when a real second case demands it. Premature abstraction costs more to read and change than the duplication it avoids.
