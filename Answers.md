## 1

Version 1 Oil cannot be migrated automatically because we have insufficient information to decide whether it means version 2 Oil or Grease. The polygon identifies the marked area, but does not tell us the type of stain. These annotations should be flagged for someone to inspect the original images and relabel them. Until resolved, they should be excluded from a v2 training export.

Labels whose meanings and geometry requirements did not change can be migrated automatically. Slub can also be mapped to Defect/Yarn/Thick place, because v2 explicitly declares that replacement.

Knot was removed without a declared replacement, so it requires human review rather than an automatic mapping.

I would preserve the original taxonomy version, label and geometry, and record any migration separately with the mapping rule used. To reproduce a dataset exported before the change, I would retain its files and a manifest recording the exact annotation event IDs, source-file hashes, taxonomy and mapping rules, selection rules and train/test assignments. Later corrections would produce a new release rather than change the old one.



