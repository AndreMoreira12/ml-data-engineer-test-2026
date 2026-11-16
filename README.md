# ML Data Engineer at Smartex | Technical test 2026

## Introduction

This is a hiring exercise, not a production project. We want to see how you model messy data, how you build a pipeline you would trust, and how you explain your decisions.

You have **72 hours** from receiving this document. We expect about 8 to 10 hours of focused work in total, so do not go far beyond that. A clear partial solution with honest notes beats a complete one that hides its gaps.

You may use any tools, including AI coding assistants. We only ask that you understand everything you submit. The next step is an in-person session where you drive a demo of your solution and we ask about the reasoning behind it. We will also ask you to change something live.

Ask questions in the thread you received this from. Where the brief is ambiguous and you would rather not wait, make an assumption, write it down, and move on. Written assumptions are part of what we assess.

### Deliverables

1. A Git repository (private GitHub or GitLab link, or a zip that includes the `.git` folder). Keep your commit history; we read it.
2. A `README.md` in the repository that covers:
   - how to run everything
   - what you built and what you skipped
   - your assumptions
   - what you would do with another day
3. Answers to the questions in Part 0, as a PDF or as `ANSWERS.md` in the repository.
4. A short `AI.md`: what you used AI for, and one place where you rejected or corrected its output.

Send the link to **miguel.gomes@smartex.ai** and **rita.santos@smartex.ai**.

## Context

Smartex builds cameras that inspect fabric on weaving machines and find defects. The cameras capture frames of the fabric as it is produced. A team of labellers then uses a web tool to mark defects on those frames, and the labelled data is exported to train detection models.

This role owns the data side of that loop: getting frames and labels in, keeping them clean, measuring the labelling work, and delivering a dataset the ML team can train on. You will not build or train models in this test or in the job.

The files in `data/` are a synthetic export from a labelling tool like ours. The volumes are small, but the problems in it are real ones.

### Data

| File | What it holds |
|------|---------------|
| `frames.csv` | One row per captured frame. A frame belongs to a fabric roll, a machine, a camera position and a light type. `height_px` and `width_px` give the frame size. |
| `annotation_events.jsonl` | One JSON object per line. Each line is one saved version of a sample. |
| `label_tree_v1.yaml`, `label_tree_v2.yaml` | The defect taxonomy. Version 2 replaced version 1 on 2026-07-01; the header of the v2 file lists what changed. |
| `annotators.csv` | The labelling team. |
| `coverage_targets.csv` | How many labelled samples the ML team wants per v2 label. |

A **sample** is what a labeller labels: one frame, or two frames of the same spot taken under different light. Each save creates a new **version** of the sample. The fields of an event are:

- `event_id`: unique id of this version.
- `sample_id`, `frame_ids`: the sample and its frames.
- `annotator_id`, `session_id`: who saved it, in which working session.
- `pass`: `first` for the initial labelling, `second` for an independent review by another labeller.
- `status`: `committed` when the labeller submitted the session, `draft` when the session was never submitted.
- `supersedes_event_id`: the version this one replaces, or `null` for the first version.
- `saved_at`: when the version was saved.
- `exporter_version`: version of the tool that wrote the line. Exporter 1.4 wrote the plant's local time (Portugal) without an offset.
- `label_tree_version`: which taxonomy the labeller's tool was using.
- `instances`: the labels on the sample. Each has a `label` path and a `geometry` of type `polygon`, `point` or `null`. Coordinates are `[row, column]` in pixels, with `[0, 0]` at the top-left corner.

The label tree says which geometry each label needs. `Normal` takes no geometry.

## Part 0: questions

Answer all six. Half a page each is plenty; bullets and a small diagram are fine.

1. **Taxonomy change.** Version 2 narrowed `Defect/Stain/Oil` and added `Defect/Stain/Grease`. Which existing labels can you migrate automatically, and which need a person to look again? How do you keep a dataset exported before the change reproducible after it?
2. **Growth.** Next year this export grows to about 50 million events per year from 40 installations, and it arrives continuously instead of as a file. What in your pipeline changes, what stays, and where would you run it?
3. **Concurrent edits.** Two labellers can save conflicting versions of the same sample. How should the labelling tool and its backend prevent or resolve this? Compare at least two approaches and say which you would pick.
4. **Trust in a number.** The Head of Data says the Grafana panel "samples labelled this week" is 12% higher than the labelling team's own spreadsheet. How do you find out which number is right?
5. **Owning the tool.** In your first month you take ownership of the labelling tool. Labellers say it feels slow and that they lost work once. What do you measure first, and in what order do you act?
6. **Handoff to training.** What does the ML team need from you, beyond the files, to trust a training export? Think about what a dataset release should carry with it.

## Part 1: ingestion pipeline (Python)

*About 3 hours.*

Load everything in `data/` into PostgreSQL with a Python pipeline.

1. Design a relational schema for frames, samples, versions, instances, annotators and both label trees. Store geometry in a form you can query. PostGIS is welcome but not required.
2. Validate every record. A record that fails is kept in a quarantine table with a reason code, never dropped silently. Decide for each problem whether to reject, repair, or accept with a flag, and write down why.
3. Normalise what needs normalising, including timestamps (store UTC) and label paths.
4. Resolve the **current state** of each sample from its version history. Decide how drafts, reviews and conflicting histories count.
5. Map version 1 labels onto version 2 where the mapping is safe, and flag the rest.
6. Make the pipeline **idempotent**. Running it twice on the same files leaves the database exactly as after one run. Running it on a later export that overlaps this one only adds what is new.
7. Print or store a validation report: how many records passed, and how many failed for each reason.

Write tests for the parts that are easy to get wrong. We care more about which parts you chose to test than about coverage numbers.

## Part 2: training export

*About 1 hour.*

Produce a training snapshot from the database.

- Include only samples you would trust for training, and state your rules.
- Use version 2 labels only.
- Split the snapshot into train (about 80%) and test (about 20%) so that the same split comes out every time, and nothing leaks between the two sets.
- Write the snapshot to files in a format of your choice, with a manifest that holds:
  - an identifier
  - the source export
  - the rules applied
  - counts per label and per split
  - enough information to rebuild the same snapshot later

## Part 3: SQL

*About 1 hour.*

Put these queries in `queries.sql`. Each should run against your schema, with a one-line comment on how it handles the tricky cases.

1. The current label of every sample.
2. Samples first-labelled per annotator per day, using the plant's local day.
3. For each annotator, how often a second pass disagreed with their first pass. Define "disagree", and use only samples that had a real second pass.
4. Coverage against `coverage_targets.csv`: current count, target, and percentage for each label.
5. The second-pass backlog: samples that should get a second pass and have not, bucketed by how long they have waited.

## Part 4: review API and page (Python and TypeScript)

*About 3 hours.*

Labellers need a page to pick their next review and to see what happened to a sample.

**Backend.** A small Python API (FastAPI preferred) over your database with:

- `GET /review-queue`: samples waiting for a second pass. Filters for label and minimum age, and a stable ordering you can page through.
- `GET /samples/{sample_id}`: current state, frames with their size, and the full version history with who changed what.

**Frontend.** A single-page app in TypeScript, **Angular** (our labelling tool uses it) or React. It shows:

- The review queue, with the filters above.
- A sample detail view. Draw the current geometry to scale inside a box the size of the frame (SVG or canvas; there are no images). Show the version history as a timeline, and show any quality flags your pipeline raised.

We are not grading visual polish. We are grading whether the page is correct, readable code, and whether a labeller could use it.

## Part 5: dashboard (Grafana)

*About 1.5 hours.*

`docker compose up` should start PostgreSQL, run your pipeline, start your API and frontend, and start Grafana with the data source and dashboard **provisioned from files in the repository**. We should not have to click anything in Grafana.

The dashboard is for the Head of Data and the labelling coordinator. At minimum, show:

- labelling throughput over time, per annotator
- the second-pass backlog
- coverage against targets
- data quality: rejected and flagged records per reason
- second-pass disagreement per annotator

Choose chart types deliberately. In your README, name one thing the dashboard reveals about this data that you would raise with the team, and say which panel shows it.

## How we assess

| Area | What we look for |
|------|------------------|
| Data modelling and SQL | A schema that fits versioned labels; correct handling of history, time zones and duplicates |
| Pipeline | Idempotent runs; quarantine instead of silent loss; decisions written down |
| Training export | Reproducible, leak-free split; a manifest someone else could trust |
| Backend | Clean API design; tests aimed at the risky logic |
| Frontend | Correct geometry rendering; readable TypeScript; usable for a labeller |
| Dashboard | Provisioned as code; panels that answer the team's questions |
| Communication | Honest README, clear answers, sound trade-offs |
| Live session | You can explain and change your own code |

Partial solutions are normal. If you run short of time, say what is missing and how you would finish it.
