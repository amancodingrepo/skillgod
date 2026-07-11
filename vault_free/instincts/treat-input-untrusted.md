---
name: Treat all external input as untrusted
type: instinct
tags: [security, input, safety]
triggers: [input, user, request, external, data]
description: Use when consuming any input from outside your own code
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Treat every input from outside your own code as untrusted by default: user data, network responses, environment, files, tool output. Assume it may be malformed or hostile until validated. Trust is earned at a boundary check, never granted by where the data appears to come from.
