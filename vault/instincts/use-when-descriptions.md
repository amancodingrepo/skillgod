---
name: Skill descriptions must start with Use when
type: instinct
tags: [skills, format, descriptions, vault]
triggers: [skill, description, write, create, add]
description: Use when writing or editing any skill file in the vault
confidence: 0.98
source: skillgod-core
created: 2024-01-01
uses: 0
---
Every skill description field must start with "Use when [triggering conditions]".
Never summarise what a skill does in the description.
Wrong: "Systematic approach to debugging Python errors"
Right: "Use when a Python script throws errors or behaves unexpectedly"
This is the single most important format rule. Wrong descriptions break discovery.
