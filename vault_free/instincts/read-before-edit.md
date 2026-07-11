---
name: Read real file contents before editing
type: instinct
tags: [safety, editing, accuracy]
triggers: [edit, modify, change, update, patch]
description: Use when about to modify an existing file
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Read a file's actual current contents before editing it. Never edit from memory or assumption about what it contains: files drift, and stale assumptions corrupt real code. Confirm the exact text you intend to change exists as you expect before changing it.
