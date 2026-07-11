---
name: Flag injection-prone patterns proactively
type: instinct
tags: [security, injection, review]
triggers: [sql, eval, shell, render, query]
description: Use when you see string-built queries, eval, or unsanitized output
confidence: 0.95
source: skillgod-core
created: 2026-07-11
uses: 0
---
Proactively flag injection-prone patterns: string-concatenated SQL, eval on input, shell=True with interpolation, unescaped HTML output (XSS), user-controlled URLs in server requests (SSRF). Prefer parameterized queries, safe APIs, and escaping. Don't wait to be asked: naming the risk is part of the job.
