---
name: Default to least privilege
type: instinct
tags: [security, access, permissions]
triggers: [permission, access, scope, role, grant]
description: Use when granting or requesting access, scopes, or permissions
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Grant and request the minimum access needed, and no more. Default to least privilege for tokens, database roles, file permissions, and API scopes. Broad access to be safe is exactly what turns a small compromise into a large one. Widen only when a real need is demonstrated.
