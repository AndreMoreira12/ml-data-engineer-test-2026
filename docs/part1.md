# Design notes

Data understanding and schema sketch.

## Agreed assumptions and rules

- A sample has fixed frame membership. Changing its frames requires a new sample ID.
- Preserve original source records, labels, taxonomy versions and geometry. Never silently overwrite conflicting evidence.
- Identical repeated events count once. Different payloads under the same event ID are quarantined; neither wins by file order.
- Unknown annotators, missing frames and inconsistent frame membership quarantine the affected version.
- If one instance is invalid, quarantine the entire version: accepting only part could hide a reported defect.
- Keep drafts in history, but exclude them from accepted current state.
- A second pass must come from a different annotator than the first pass being reviewed. Self-review quarantines the version.
- A valid committed second pass can be accepted even if its first-pass predecessor was a draft.
- Every training sample needs a valid committed independent second pass. This is our chosen restriction, not an explicit requirement of the brief.
- Different valid committed branches require human resolution. Agreeing branches can share current annotation when frames, taxonomy, labels and geometry match; preserve both events. Instance order alone does not create disagreement.
- An earlier valid version can remain visible when a later save is quarantined, but the unresolved issue blocks training.
- V1 Oil cannot safely become v2 Oil or Grease without human inspection: its meaning changed. Keep it valid as v1, but unresolved for v2 training.
- The explicit v1 Slub to v2 Yarn/Thick place replacement supports automatic migration.
- Resolving an issue means preserving its evidence and recording the correction and explanation, preferably through a new event. Recheck all eligibility rules afterward.
- Corrections can affect a new dataset release; existing releases must remain unchanged.

## Schema sketch — proposed, not final

| Table | Key / relationship |
|---|---|
| frames | frame_id; roll, machine, camera, light, timestamp, dimensions |
| samples | sample_id |
| sample_frames | (sample_id, frame_id); references samples and frames |
| annotators | annotator_id; identity and active dates |
| taxonomy_versions | version; release date |
| taxonomy_labels | (version, label_path); meaning, geometry requirement, deprecation |
| annotation_versions | event_id; sample, annotator, session, pass, status, parent ID, UTC timestamp, taxonomy |
| instances | (event_id, instance_index); original label and geometry |
| label_mappings | Original label, target label where safe, rule and review status |
| coverage_targets | V2 label and target sample count |
| source_files / source_records | File-content identifier and row number; preserve original input |
| quarantine / quality_flags | Reasons, affected records, resolution status and explanation |

Raw records preserve evidence; relational tables hold validated, queryable data. Valid drafts may be stored there without becoming current. Geometry as PostgreSQL jsonb is proposed. Coordinates remain [row, column]; rendering uses x=column and y=row.


## Evidence checked (Using GPT Sol 6.1)

- 3,860 frame rows, 3,927 event lines, 2,658 distinct sample IDs.
- 96 repeated event IDs: 90 with identical parsed payloads; six with conflicting payloads.
- Nine samples have changing frame sets; each references a missing frame. Four event lines list three frames, exceeding the brief's one-or-two-frame definition.
- 169 draft event lines; unknown annotator A12 appears in events.
- Nine parents have multiple distinct children. No missing parents, cross-sample parent links or cycles found in the source history.
- No frame was referenced by multiple distinct samples.
- Sample smp_001097: A11 first pass, A01 committed second pass, same Broken end label but different polygons. The second event is repeated identically. Both versions reference frm_001374.

These are exploratory results, not a complete validation report.

## Missing checks and decisions

- Complete timestamp inspection and Europe/Lisbon conversion, including daylight-saving edge cases; capture/save chronology.
- Label spelling normalization and remaining taxonomy mappings, including Knot and deprecated v2 Slub.
- Geometry structure, bounds and paired-frame coordinate interpretation; exact polygon-equivalence comparison.
- Final current-state algorithm: multiple roots, deeper branches, quarantined ancestors and later corrections.
- How fixed membership is established when source declarations disagree; duplicate frame metadata and frame reuse constraints.
- Disagreement metric: labels only or geometry too? Should a draft first pass be used as a comparison baseline?
- First-labelled attribution, coverage counting and review queue eligibility, age and ordering.
- Reproducible release manifest and leakage prevention across related samples, frames and rolls.
- Idempotent handling when a later export conflicts with a previously accepted event, including issue deduplication.

