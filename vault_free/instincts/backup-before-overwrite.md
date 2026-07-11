---
name: Back up irreplaceable data before overwriting
type: instinct
tags: [safety, data, migration]
triggers: [migrate, overwrite, reset, replace, wipe]
description: Use before overwriting or migrating data or config that cannot be regenerated
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Before overwriting, migrating, or resetting data or config that cannot be regenerated, back it up first. A failed migration with a backup is an inconvenience; without one it is data loss. Prefer writing to a new location over destroying the original in place.
