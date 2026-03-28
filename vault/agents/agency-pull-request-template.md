---
name: PULL_REQUEST_TEMPLATE
type: skill
source: agency-agents
description: Use when ## What does this PR do?  <!-- Brief description of the change -->  ## Agent Information (if adding/modifying an agent)
tags: [agent]
triggers: [what, does, brief, description]
confidence: 0.8
uses: 0
---

## What does this PR do?

<!-- Brief description of the change -->

## Agent Information (if adding/modifying an agent)

- **Agent Name**:
- **Category**:
- **Specialty**:

## Checklist

- [ ] Follows the agent template structure from CONTRIBUTING.md
- [ ] Includes YAML frontmatter with `name`, `description`, `color`
- [ ] Has concrete code/template examples (for new agents)
- [ ] Tested in real scenarios
- [ ] Proofread and formatted correctly
