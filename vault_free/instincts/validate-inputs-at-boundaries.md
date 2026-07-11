---
name: Validate inputs at trust boundaries
type: instinct
tags: [security, validation, input]
triggers: [input, validate, request, parse, boundary]
description: Use when data enters the system from an external source
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Validate and sanitize data at the boundary where it enters (user input, request bodies, file contents, third-party responses) before it flows into logic, queries, or storage. Never assume external data is well-formed. Boundary validation is where most injection and corruption bugs are cheaply stopped.
