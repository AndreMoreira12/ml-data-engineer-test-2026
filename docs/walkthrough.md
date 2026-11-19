
# Read this first

The pipeline answers three questions: **what did the export contain, which saved versions are valid, and which annotation is current?** Keeping them separate is the main design choice.

## Evidence comes first

All six `data/` files remain unchanged. `source_files` stores exact bytes and a SHA-256 fingerprint: an identity based on content, not filename. `source_records` preserves CSV rows, JSONL lines and taxonomy documents.

One event line is a source occurrence, not necessarily a new version. Overlapping exports can repeat it. `event_payloads` stores distinct parsed payloads under each event ID; `event_occurrences` links every source line to its payload. Identical parsed evidence counts once. Different payloads claiming one ID all receive `CONFLICTING_EVENT_ID`; neither wins.

Read `pipeline/events.py`. Root `ingest.py` is only the launcher; `pipeline/ingest.py` coordinates the load.

## References make checks meaningful

Annotators establish identities/active dates. Frames supply capture metadata and dimensions. Taxonomies define label paths and geometry requirements. Targets specify desired counts.

We normalize light spelling and timestamps, but do not infer missing dimensions. Conflicting dimensions make a frame unusable until resolved. Nearby captures can support investigation, not overwrite evidence. Read `pipeline/frames.py` and `pipeline/taxonomy.py`.

## Parsing is not validation

A JSON object may reference an unknown author, absent frame, unknown label or invalid shape. `pipeline/validation.py` collects those checks. Coordinates are `[row,column]`: row uses height, column uses width. They are never clipped or swapped to pass validation.

One bad instance quarantines the whole saved version. `quarantine` holds reasons; `validation_details` retains failing instance positions where relevant. Complete original payloads remain available. Only passing versions populate `annotation_versions` and `instances`.

UTC identifies instants consistently; Lisbon local days matter for active-date checks and future daily reporting. `pipeline/timestamps.py` handles clock changes too.

## History is not a timestamp sort

`supersedes_event_id` names a parent. Check missing/conflicted parents, wrong samples, cycles and backwards chronology. Parent evidence can exist only in quarantine; it need not exist in valid-version tables.

A second pass must trace to a first pass by another author. That first pass may be draft. Its invalid geometry doesn't erase otherwise reliable authorship, though unresolved history problems still block training.

Current state considers valid committed versions. Valid committed descendants supersede their committed ancestors, even through drafts. A draft or invalid later save does not erase an earlier valid commit. Disagreeing committed leaves produce `conflict`. Matching leaves preserve all contributors; lexical ID chooses a display representative only.

Read `pipeline/history.py`, then `pipeline/domain.py`. `sample_state` has one row per observed sample; `current_contributors` keeps authorship.

## Current is not training-ready

Each valid instance retains its original label, taxonomy and geometry, plus a separate v2 target/status/rule. Slub maps to Thick place because replacement is explicit. V1 Oil included greasy stains too, so it cannot safely become narrowed v2 Oil. Knot lacks a replacement.

These can be valid current annotations needing migration review. Training eligibility additionally requires an independent committed review, safe mappings and no unresolved quarantined history. No training release/manifest has been created. Read the short `pipeline/migration.py` allowlist.

## Counts have different units

3,927 event lines represent 3,831 IDs. There are 3,402 valid versions and 3,976 valid instances; instances are labels/shapes, not samples. Of 2,658 observed samples, 2,392 have resolved current state, two have branch conflicts and 264 lack a valid committed current version. The strict training rule leaves 695 eligible samples.

444 event lines are quarantined. A line can have several reasons, so summing reason counts overstates rejected lines. Coverage counts distinct resolved samples per safely mapped v2 label; it is broader than training eligibility.

## Reruns are normal

Stable keys prevent duplicate evidence/issues. Later exports can reveal conflicts in earlier accepted IDs. Small derived tables are rebuilt in one transaction; failure rolls back rather than leaving half a current state. This straightforward scan/rebuild fits the exercise, not streaming scale.

Quarantine does not clear automatically. That is visible/conservative, but an audited resolution workflow is still needed. Use [database.md](database.md) to trace a sample, then [exercise.md](exercise.md) to practice explaining it.
