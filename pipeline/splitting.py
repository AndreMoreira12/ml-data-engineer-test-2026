"""Stable roll assignment; related samples must use their roll's split."""

import hashlib


SPLIT_SEED = 'smartex-roll-split-v1'


def split_for_roll(roll_id, seed=SPLIT_SEED):
    """Assign approximately 20% of rolls to test, without depending on input order."""
    if not isinstance(roll_id, str) or not roll_id.strip():
        raise ValueError('A nonempty roll ID is required')
    digest = hashlib.sha256(f'{seed}:{roll_id}'.encode('utf-8')).digest()
    return 'test' if int.from_bytes(digest, 'big') < (1 << 256) // 5 else 'train'
