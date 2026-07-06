---
name: Each agent gets its own skill injection
type: instinct
tags: [agents, skills, injection, multi-agent]
triggers: [spawn, agent, swarm, orchestrate, parallel]
description: Use when spawning any specialist agent for a subtask
confidence: 0.97
source: skillgod-core
created: 2024-01-01
uses: 0
---
When spawning specialist agents, always call get_skills_for_agent(agent_type, task)
for each agent individually. Never inject the parent task's skills into child agents.
Frontend agent gets UI skills. Backend agent gets API skills. This is non-negotiable.
