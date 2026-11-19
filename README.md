# Annotation ingestion and training export

This is a partial solution to the [Smartex challenge](docs/challenge.md). It loads
the six supplied files into PostgreSQL, preserves evidence, validates annotations,
resolves version history, and exports a reproducible v2 training dataset.

I used AI for most of the implementation. My work on the exercise included trying
to understand the brief and dataset, asking questions, discussing decisions and
giving feedback. With the time I had, I could not fully understand every detail
of the generated solution. My experience is closer to Python, SQL and industrial
data; frontend development and some of the infrastructure are less familiar to
me. I am submitting this as a partial, AI-assisted exercise, with those limits
made explicit. The technical descriptions below document the implementation;
they are not a claim that I wrote or independently verified every part.


## Run

With Docker Desktop running, execute from the repository root:

```powershell
docker compose up --build
```

PostgreSQL becomes healthy before the one-shot pipeline starts. The pipeline
prints a JSON validation report and exits; PostgreSQL stays running. Check that
the pipeline exited with code 0:

```powershell
docker compose ps -a
docker compose logs pipeline
```

Rerun ingestion without resetting the database:

```powershell
docker compose run --rm pipeline
```

The pipeline applies schema scripts to existing databases as well as new ones.
Keep the database volume: deleting it removes accumulated evidence. These scripts
support the current schema, not arbitrary future schema changes.

For local Python, use Python 3.11+ and the running Compose database. The Docker
image uses Python 3.14. Commands below use PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = 'postgresql://smartex:local-demo@127.0.0.1:5432/smartex'
.venv\Scripts\python.exe ingest.py
.venv\Scripts\python.exe -m unittest -v
.venv\Scripts\python.exe -m pipeline.export
```

The local database is exposed on `127.0.0.1:5432`, database/user `smartex`, password
`local-demo`. For a later complete export, use `ingest.py --data-dir path/to/export`
with the same six filenames. No model is trained.

## Data flow and database

An event is a saved version, a sample contains one or two frames, and an instance
is one label and its geometry within a version. They are different counting units.

```text
Six source files
  -> exact file bytes and source records
  -> validation and quarantine
  -> accepted annotation versions and instances
  -> resolved current sample state and coverage
  -> eligible samples -> frozen train/test release
```

The definitions are in [sql/](sql/). Primary keys prevent repeated identities;
foreign keys connect related rows. Python adds rules that keys alone cannot
enforce, such as independent authorship and valid ancestry.

| Tables / views | Purpose and identity |
| --- | --- |
| `source_files`, `source_records` | Exact bytes keyed by file SHA-256; original records keyed by file hash and row number. Source data stays unchanged. |
| `quarantine`, `validation_details` | Rejection reasons per source record, with instance positions/details where available. One record can have several reasons. |
| `event_payloads`, `event_occurrences` | Parsed variants keyed by event ID and payload hash; occurrences connect each source line to its variant. Repeated exports do not multiply saves. |
| `annotators`, `frames` | Typed reference data: active dates, roll/machine/camera/light, UTC capture time and dimensions, with source provenance. |
| `taxonomy_versions`, `taxonomy_labels`, `coverage_targets` | Both original trees and leaf definitions keyed by version/path; targets per v2 label. |
| `samples`, `sample_frames` | Observed sample IDs and validated frame membership. A sample can exist even when all its versions fail. |
| `annotation_versions`, `instances` | Accepted unique saves including drafts, keyed by event ID; instances keyed by event ID and position. Original/normalized labels, JSONB geometry and separate v2 migration results are retained. |
| `sample_state`, `current_contributors`, `quality_flags` | Resolution (`resolved`, `conflict`, `no_current`), representative event, all agreeing current saves, training eligibility and sample-level warnings. |
| `event_candidates` (view) | Unique, unconflicted events with no quarantined occurrence; an intermediate selection, not current state. |
| `current_coverage` (view) | Distinct resolved current samples per safely mapped v2 label, target and percentage. Review is not required for this operational count. |

Reference rows can remain stored after conflicting evidence quarantines their
provenance. Presence alone does not prove usability; loaders exclude quarantined
references. Parent/review-baseline IDs can point to raw evidence rather than
accepted versions, so Python checks those relationships.

The seven derived domain tables from `samples` through `quality_flags` are rebuilt
together within the ingestion transaction. Failure rolls back the load. Evidence
and historical quarantine persist. Ingestion is sequential and rereads accumulated
evidence; this is a small local implementation.

## Ingestion rules and trade-offs

These are implementation choices where the brief leaves room for interpretation.

| Area | Chosen behavior and reason | Limitation / alternative |
| --- | --- | --- |
| Validation | Quarantine the whole saved version if any instance fails; preserve all original instances in evidence. | Partial acceptance could retain useful labels but hide a rejected defect. |
| Duplicate IDs | Identical parsed payloads count once; ignore formatting/key order. Different payloads under one ID quarantine all occurrences. | No automatic winner; array order and original values remain significant. |
| Overlapping exports | Stable file/record/payload keys prevent duplicate evidence. Later conflicts invalidate derived state. | New evidence can change current results; accepted tables are not append-only. |
| Reference / membership conflicts | Preserve evidence and exclude the conflicting identity. Compare unordered sample frame sets across exports, including invalid versions. | File order cannot choose the correct declaration. |
| Time | Exporter 1.4 and naive captures use `Europe/Lisbon`; observed integers are Unix milliseconds. Store UTC; quarantine ambiguous/nonexistent DST times. Active dates include the entire Lisbon boundary day. | Local reports must convert UTC to Lisbon before grouping by day. |
| Paired frames | Same roll, machine, camera and dimensions, different light. Assume alignment; coordinates must fit both. | Capture times need not match exactly; no supplied images prove alignment. |
| Geometry | Preserve `[row, column]` in JSONB. Require finite, in-bounds coordinates, matching geometry type and simple nonzero-area polygons. `Normal` is the sole instance with null geometry. | A renderer would use x = column, y = row and preserve scale; none is implemented. |
| History | Check missing/conflicting parents, cycles, cross-sample links and reversed time order. A second pass needs a first-pass ancestor by another author. | Draft first passes are allowed; an ancestor with invalid geometry can still establish authorship. |
| Current state | Valid committed leaves supersede committed ancestors. Drafts/invalid saves cannot erase a valid commit. Agreeing branches keep all contributors; differing ones remain conflicts. | Agreement uses source taxonomy, normalized labels, frames and exact coordinates, ignoring instance/frame order. No geometric tolerance. Lexical ID chooses only a display representative. |
| Normalization | Match case/slash spacing only to a unique taxonomy path; retain original text. | No fuzzy typo repair; deprecated labels can remain valid history. |
| Migration | Explicit allowlist for unchanged v1 meanings; Slub maps to Thick place. V1 Oil and removed Knot require review. Store mapping separately. | Shared paths do not establish shared meaning; Oil needs image inspection/relabeling. |
| Training | Resolved state, independent committed review contributor, safe v2 mappings, no quarantined sample history. | Stricter than the brief; old unresolved errors can block corrected samples. |
| Issue resolution | Quarantine persists. | No audited command clears resolved issues; corrections do not silently erase reasons. |
| Coverage | Distinct resolved samples once per safely mapped label. One sample may count for several labels. Zero target gives null percentage. | Includes samples awaiting review; coverage is not training dataset size. |

## Training release

`python -m pipeline.export` writes `exports/<release_id>/` and prints its path and
counts. Generated releases are ignored by Git; regenerate for the demo or include
a release separately when handing a dataset to the ML team.

- `train.jsonl`, `test.jsonl`: one object per sample, with frames, v2 labels,
  geometry, event/payload identities, original labels and review provenance.
  Use `instances[].label` as the training target.
- `taxonomy-v2.json`: frozen v2 definitions.
- `manifest.json`: source hashes, selection/split rules, exact sample/event/roll
  membership, per-label sample/instance counts, file checksums and release ID.
- `sources/<sha256>.bin`: exact source bytes known to the database at export time;
  the manifest preserves original filenames.

The exporter reads a PostgreSQL repeatable-read, read-only snapshot so concurrent
ingestion cannot mix database states. SHA-256 of a fixed seed and roll ID assigns
approximately 20% of rolls to test. All samples and paired frames from a roll stay
together; shared frames crossing splits fail the export. New rolls do not move
existing ones. This evaluates unseen rolls; it does not guarantee balanced labels
or independence between machines or fabric types.

Identical snapshots produce identical bytes and a content-based release ID.
Reruns verify and reuse an identical release, refusing to overwrite differences.
A staging directory is renamed into place after writing. Checksums detect manual
changes; local files are not immutable storage.

Keep the whole release and the repository version used to produce it. After later
ingestion, frozen files and manifest membership remain the authority: selecting
again from live `sample_state` may produce a different dataset. Raw sources alone
cannot guarantee the same selection under changed code or accumulated quarantine
history. No image pixels are supplied.

## Results and inspection

The recorded [validation report](docs/validation-report.json) contains 3,927 event
line occurrences, 3,831 distinct event IDs and six conflicting IDs. It reports
3,402 accepted versions and 3,976 instances across 2,658 observed samples:
2,392 resolved, two conflicting and 264 without valid committed current state.
444 event lines are quarantined; reason counts overlap.

The inspected training snapshot contains 695 eligible samples across 108 rolls:
541 train (85 rolls) and 154 test (23 rolls), or 22.2% test. Only two test samples
carry Starting mark, which limits evaluation for that label.

A finding to raise with the team: v1 Oil includes meanings now split between Oil
and Grease. Counting all of it as v2 Oil would misrepresent coverage. Inspect
`instances.mapping_status` and `quality_flags`. No Grafana panel exists to cite
because the dashboard requirement is unfinished.

Open the SQL terminal:

```powershell
docker compose exec db psql -U smartex -d smartex
```

Inspect counts and trace one sample from evidence to current state:

```sql
SELECT status, count(*) FROM sample_state GROUP BY status;
SELECT count(*) FROM sample_state WHERE training_eligible;
SELECT * FROM current_coverage ORDER BY label_path;
SELECT reason_code, count(*) FROM quarantine GROUP BY reason_code;

SELECT row_number, raw_text FROM source_records
WHERE sample_id = 'smp_001097' ORDER BY source_file_id, row_number;
SELECT event_id, annotator_id, pass, status, saved_at, supersedes_event_id
FROM annotation_versions WHERE sample_id = 'smp_001097'
ORDER BY saved_at, event_id;
SELECT * FROM sample_state WHERE sample_id = 'smp_001097';
SELECT * FROM quality_flags WHERE sample_id = 'smp_001097';
```

Exit psql with `\q`. Quarantine rows count reasons, not distinct bad records.

## Verification and remaining work

On 2026-11-19, all **57 tests passed locally with PostgreSQL enabled**. Tests cover
timestamps/DST, validation, geometry, taxonomy, lineage, independent reviews,
duplicates/overlaps, transaction rollback, snapshot replay, overwrite protection
and sample/roll/frame split leakage. Database fixtures roll back; the end-to-end
pipeline test initializes a private schema. Without `DATABASE_URL`, eight database
tests are skipped; that is not full verification.

Compose inspection showed a healthy database and an existing successful pipeline
container. A fresh-volume Compose boot and the new exporter's execution inside
the image were not checked in this review. Earlier ingestion verification recorded
48 passing tests inside the Linux image; this does not establish that the current
57-test suite passed there.

With another day, I would focus on understanding and simplifying the existing
pipeline, tracing samples through it, and writing the required SQL queries with
clear metric definitions. The API, TypeScript page and Grafana would still need
work, and I would need learning time or support for the unfamiliar parts. I would
not promise to complete all of them in that day. An audited way to resolve old
quarantine issues is another limitation to address.

Start reading code at [pipeline/ingest.py](pipeline/ingest.py), then
[pipeline/domain.py](pipeline/domain.py), [pipeline/history.py](pipeline/history.py)
and [pipeline/export.py](pipeline/export.py). See [AI.md](AI.md) for assistance
disclosure and [ANSWERS.md](ANSWERS.md) for Part 0.
