"""
In-memory motif catalog lookup.

Provides a thin wrapper for loading and querying the motif score catalog
from MongoDB. Designed to be loaded once in the main process and passed
to workers via shared_ctx.
"""

import logging
from typing import Dict


def load_motif_scores_for_workers(database, min_composite: float = 0.02, min_zscore: float = 1.96) -> Dict[str, float]:
    """
    Load scored motifs from MongoDB as a flat dict for worker processes.

    This is loaded once in the main process and passed via shared_ctx.
    Workers use it to look up scores by motif_key without DB access.

    Returns:
        Dict mapping 'motif_key_window' (e.g. 'U3M:D1S:U2L_40') to composite_score.
    """
    if database is None:
        return {}

    try:
        collection = database['motif_catalog']
        cursor = collection.find(
            {
                'composite_score': {'$gt': min_composite},
                'edge_zscore': {'$gt': min_zscore},
            },
            {'motif_key': 1, 'composite_score': 1, '_id': 0}
        )
        scores = {doc['motif_key']: doc['composite_score'] for doc in cursor}
        if scores:
            logging.info("Loaded %d motif scores for workers", len(scores))
        return scores
    except Exception as e:  # pylint: disable=broad-except
        logging.warning("Failed to load motif scores: %s", e)
        return {}


def lookup_motif_score(
    motif_scores: Dict[str, float],
    motif_key: str,
    window_size: int,
) -> float:
    """
    Look up a motif's composite score from the pre-loaded dict.

    Args:
        motif_scores: Pre-loaded {motif_key_window: score} dict.
        motif_key: The motif key string (e.g. 'U3M:D1S:U2L').
        window_size: Window size used for segmentation.

    Returns:
        Composite score, or 0.0 if not found.
    """
    key = f"{motif_key}_{window_size}"
    return motif_scores.get(key, 0.0)
