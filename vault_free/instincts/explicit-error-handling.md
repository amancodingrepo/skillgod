---
name: Handle errors explicitly, never swallow them
type: instinct
tags: [quality, errors, reliability]
triggers: [error, exception, catch, fail, handle]
description: Use when writing code that can fail
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Handle error and failure paths explicitly. Never swallow an exception with an empty catch, ignore a returned error, or let a failure pass silently. Either handle it meaningfully or let it surface loudly. Silent failure is the most expensive kind: it hides the real problem until far downstream.
