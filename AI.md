# AI assistance

I used OpenAI Codex during the initial data-understanding and schema-design milestone.

## What I used it for

- Reading the challenge and inspecting the supplied CSV, JSONL and YAML files. Codex ran exploratory PowerShell checks for duplicate events, frame membership, drafts and version-history relationships.
- Learning through small exercises: tracing a sample, distinguishing export lines from annotation versions, and understanding keys, relationships, quarantine and taxonomy migration.
- Discussing a proposed PostgreSQL schema and the trade-offs behind validation, independent review, current-state resolution and training eligibility.

## A recommendation I rejected

Codex recommended accepting a completed second-pass review only if the first pass had been committed. I rejected that restriction: a valid, committed independent second pass can be accepted even when its first-pass predecessor was a draft.

