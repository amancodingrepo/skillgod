---
name: Never hardcode or commit secrets
type: instinct
tags: [security, secrets, credentials]
triggers: [password, token, key, secret, credential]
description: Use when handling credentials, keys, or tokens
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Never hardcode passwords, API keys, tokens, or credentials into source, and never commit them to version control. Use environment variables or a secret store, and never log secrets. If a secret appears in code or output, treat it as compromised and flag it for rotation.
