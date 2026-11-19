"""Explicit v1 -> v2 meaning rules, kept alongside original annotation labels."""

UNCHANGED_V1 = {"Normal", "Defect/Weft/Broken pick", "Defect/Weft/Double pick",
                "Defect/Weft/Missing pick", "Defect/Warp/Broken end", "Defect/Warp/Float", "Defect/Hole"}


def migrate_label(version, path):
    if version == 2:
        if path == "Defect/Slub":
            return "Defect/Yarn/Thick place", "safe", "slub-replacement-v1"
        return path, "direct", "native-v2"
    if version != 1:
        return None, "review_required", "unsupported-source-taxonomy"
    if path == "Defect/Slub":
        return "Defect/Yarn/Thick place", "safe", "slub-replacement-v1"
    if path in UNCHANGED_V1:
        return path, "safe", "unchanged-meaning-v1"
    if path == "Defect/Stain/Oil":
        return None, "review_required", "oil-meaning-narrowed-v1"
    return None, "review_required", "no-safe-equivalent-v1"
