---
name: Never leave the code in a broken state
type: instinct
tags: [quality, safety, reliability]
triggers: [stop, finish, pause, done, commit]
description: Use when pausing or finishing a coding change
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Don't stop with the codebase in a broken, non-compiling, or half-migrated state. At any natural stopping point, leave it runnable, or clearly mark what is incomplete and why. The next session should never inherit a silent breakage it has to discover the hard way.
