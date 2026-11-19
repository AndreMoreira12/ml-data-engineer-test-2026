# Part 0 answers

These answers were developed from my thoughts in discussion with AI, which also
suggested technical details and helped with wording. They describe how I would
approach the problems, not experience I have with every system mentioned. My
stronger areas are Python, SQL and data work. Frontend development and owning
infrastructure would require more learning and support.

## 1. Taxonomy change

Version 1 Oil cannot be migrated automatically because we have insufficient information to decide whether it means version 2 Oil or Grease. The polygon identifies the marked area, but does not tell us the type of stain. These annotations should be flagged for someone to inspect the original images and relabel them. Until resolved, they should be excluded from a v2 training export.

Labels whose meanings and geometry requirements did not change can be migrated automatically. Slub can also be mapped to Defect/Yarn/Thick place, because v2 explicitly declares that replacement.

Knot was removed without a declared replacement, so it requires human review rather than an automatic mapping.

I would preserve the original taxonomy version, label and geometry, and record any migration separately with the mapping rule used. To reproduce a dataset exported before the change, I would retain its files and a manifest recording the exact annotation event IDs, source-file hashes, taxonomy and mapping rules, selection rules and train/test assignments. Later corrections would produce a new release rather than change the old one.

## 2. Growth

I would move from batch processing to processing saves as they arrive. This would let us tell the annotator if an error was found while they are still working on the sample. Some errors could then be corrected straight away, increasing the amount of usable labelled data. Checks for missing fields or coordinates outside the frame should also happen in the tool when saving. These checks would not tell us whether the annotator chose the correct defect label.

The main change to the current pipeline would be to process new events and update only the affected samples, instead of rebuilding all the tables. We would still keep the original data. If the same event arrives twice, it should only count once. If a version arrives before the version it replaces, we should keep it and check it again when the missing version arrives. Keeping the original data would also let us run the processing again after a failure or a change in the rules.

I would keep most of the validation logic, including UTC timestamps, the original taxonomy and labels, safe label mappings, independent reviews and the rules for conflicting versions. Training exports would still be saved as fixed releases. For quarantine, I would group errors by reason and installation. If one exporter bug causes thousands of errors, we should fix the cause rather than ask annotators to review each one. Questions about the correct label would go to annotators, while technical problems would go to whoever maintains the pipeline.

I would run this in the company's existing cloud environment, using managed services for PostgreSQL, a queue to hold incoming events until they are processed, and storage for the original data and training releases. I would be responsible for maintaining the pipeline, but I would need support with the initial infrastructure setup because I have not been responsible for DevOps before. I would monitor how long events take to process, failures, quarantine growth and storage usage, and check that we can recover after a failure.

## 3. Concurrent edits

I would check the version when the annotator saves. The tool would send the ID of the version they started from, and the backend would check whether it is still the current version. If someone else has saved a newer version, the annotator would be notified and the tool would load it for comparison, while keeping their unsaved changes. They could then decide what to keep and submit a new version based on the current one. We should not automatically overwrite either person's work.

The check and save need to happen as one database operation or transaction that prevents another save from slipping between them. Otherwise, two people could both pass the check before either change is saved. This approach is called optimistic concurrency control: people can edit at the same time, but a save based on an outdated version is not accepted as the new current version.

Another option would be to lock the sample while someone edits it. This prevents simultaneous edits, but it also blocks other annotators. We would need to handle abandoned locks, for example when someone opens a sample and closes their laptop, with a timeout or a way to release the lock. I would prefer checking at save time because it avoids blocking the sample for the whole editing session, although the annotator may still need to resolve a conflict.

The ingestion pipeline would remain a fallback for conflicts that already exist in exports. It would preserve both versions, flag the conflict and keep the sample out of training until it is resolved. This is the behavior implemented in this project; the backend save check described above is a proposed improvement.

## 4. Trust in a number

I would first understand what "samples labelled this week" means for each team. Are they counting distinct samples, saved versions or second-pass reviews? Do drafts, rejected annotations or later corrections count? I would also check that both numbers use the same week boundaries in Europe/Lisbon, the same annotators and installations, and the same data cutoff. Neither number should be assumed correct just because it comes from Grafana or the team's spreadsheet.

I would look at `event_occurrences` to check whether repeated exports are being counted as new work. One sample can also have several different saved versions, so even counting distinct event IDs would not necessarily give the number of labelled samples. If the spreadsheet counted raw events while Grafana counted valid samples, I would normally expect the spreadsheet to be higher. Since Grafana is higher here, that explanation alone would not fit the difference.

Once the definitions and cutoff match, I would get the sample IDs behind both totals and compare them. I would inspect examples that appear only in Grafana and examples that appear only in the spreadsheet, tracing them back to the original events. This should help show whether the difference comes from duplicates, drafts, reviews, time zones, filters, missing spreadsheet entries or a delayed refresh.

If the agreed metric is newly labelled samples, I would propose counting each sample once, when its first valid committed first-pass annotation was saved. I would find that first annotation across the full history before checking whether it falls in the week, so editing an old sample would not make it newly labelled again. I would confirm this definition with the team. If the records still do not match, I would check the panel query and ingestion pipeline, fix the cause, and compare both totals again. I would then document the definition so the same disagreement does not keep happening.

## 5. Owning the tool

I would first ask the annotators to show me how they use the tool and explain what happened. I would investigate the lost work first, because losing work is worse than the tool being slow. I would check whether their changes reached the database and whether they could be recovered.

For slowness, I would start by measuring how long saves and database queries take, since databases are closer to my experience. I would not assume the database is the cause. I would be less comfortable looking into the frontend and would need help from someone familiar with it. After a fix, I would compare the timings and ask the annotators whether the problem improved.

## 6. Handoff to training

I would give the ML team context about the rolls, machines and annotators behind the data. I would also explain which samples were included or excluded, the labels used and any known quality problems, so they understand what they are receiving.

In this project, we only include reviewed samples with labels that can safely be used in v2 and no unresolved conflicts or quarantine issues. We keep samples from the same fabric roll together: either for training or for testing, never both. This lets the ML team test on rolls the model did not see during training. I would agree this choice with them.

I would also keep a file listing what went into the export and the rules used to select it. This file is called a manifest. I would keep it with a saved copy of the exported data, so we can return to the same dataset even after new data arrives.



