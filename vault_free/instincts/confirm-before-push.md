---
name: Confirm before pushing or releasing
type: instinct
tags: [safety, git, release]
triggers: [push, release, publish, deploy, ship]
description: Use when about to push to a remote or cut a release
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Never commit-and-push to a remote repository or cut a release without explicit confirmation. Local commits are fine; publishing to shared or production surfaces is a human-gated decision. Pushing prematurely can break others' builds or ship unverified work. Ask first.
