# AI assistance

I used OpenAI Codex extensively throughout this exercise. AI generated most of
the implementation, including Python ingestion and export code, PostgreSQL
schema, tests, Docker configuration and documentation. It also helped inspect
the supplied data, discuss design choices, debug failures and run verification.

My contribution included providing context about my experience and constraints,
asking questions, supplying feedback and directing the work in small steps.
For example, I chose evaluation on unseen fabric rolls, which informed the
train/test grouping. I tried to understand the challenge and dataset, but with
the time available I did not fully understand every nuance or every part of the
generated code. Passing automated tests does not establish my understanding.

The written answers were developed through discussion: I gave my initial thoughts
and Codex helped write them. Its contribution included technical ideas and
corrections, not just grammar. Some drafts were more detailed than I felt able to
defend, particularly on tool ownership and the training handoff. I asked Codex to
shorten and simplify them and to state that I would need help with frontend work.
This was a correction to how AI presented my knowledge. These answers describe
proposed approaches, not previous experience operating all these systems.

One concrete corrected AI output was the training export's use of
`TemporaryDirectory` as a staging directory on Windows. Its restrictive
permissions survived the rename and prevented my normal account from accessing
the release. Codex changed staging to inherit the output folder's permissions.
It also fixed a misleading verification error: directory-listing permission
failures are now raised explicitly instead of making files appear missing.
The code and a regression test for permission-error reporting are in
`pipeline/export.py` and `tests/test_export.py`.

Codex also consolidated the submission documentation and ran the current local
test suite with PostgreSQL: 57 tests passed on 2026-11-19. The README distinguishes
verified behavior from checks not performed and lists unfinished deliverables.
No model was trained. Codex has not committed, published or sent this submission.
