"""Hull selection and split assignment by family.

Rules (fixed before any run):

- A family is never split across development, validation and sealed test.
- Ship-D: the 30,000 feasible hulls of the three constrained random sets are clustered by their 45
  parameters (standardised, k-means with k-means++ start, fixed seed). A cluster is a family. Whole clusters
  go to a split. The diffusion-augmented sets are not used (they come from the same hulls).
- Named hulls, each its own family: DTMB 5415, Series 60 and Wigley are development; KCS, KVLCC1 and KVLCC2 are
  the sealed test (KVLCC1 and KVLCC2 are close relatives and stay together); the Delft yacht series (DSYHS)
  is one family and the validation split.
"""
from __future__ import annotations

import hashlib

import numpy as np

SEED = 20261107
N_CLUSTERS = 44
CLUSTERS_PER_SPLIT = {"development": 26, "validation": 9, "test": 9}
CANDIDATES_PER_CLUSTER = 9  # first N that pass the feasibility check are kept
HULLS_PER_CLUSTER = 5
DSYHS_STRIDE = 1

NAMED_SPLITS = {"dtmb5415": "development", "series60": "development", "wigley": "development",
                "kcs": "test", "kvlcc1": "test", "kvlcc2": "test"}
DSYHS_SPLIT = "validation"
OVERLAY_FRACTION = 0.2
LEVELS = (0, 1, 2, 3)


def shipd_cluster_labels(vectors: np.ndarray) -> np.ndarray:
    from scipy.cluster.vq import kmeans2

    spread = vectors.std(axis=0)
    spread[spread == 0] = 1.0
    standardised = (vectors - vectors.mean(axis=0)) / spread
    _, labels = kmeans2(standardised, N_CLUSTERS, seed=np.random.default_rng(SEED), minit="++")
    return labels


def cluster_splits() -> dict[int, str]:
    order = np.random.default_rng(SEED + 1).permutation(N_CLUSTERS)
    result, position = {}, 0
    for split, count in CLUSTERS_PER_SPLIT.items():
        for cluster in order[position:position + count]:
            result[int(cluster)] = split
        position += count
    return result


def candidate_rows(labels: np.ndarray, cluster: int) -> list[int]:
    """Deterministic shuffled candidate rows of one cluster."""
    rows = np.flatnonzero(labels == cluster)
    rng = np.random.default_rng(SEED + 100 + cluster)
    return [int(r) for r in rng.permutation(rows)[:CANDIDATES_PER_CLUSTER]]


def layout_for(hull_id: str) -> str:
    """Same layout for every degradation level of a hull (paired comparison)."""
    digest = int(hashlib.sha256(f"layout:{hull_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "overlay" if digest < OVERLAY_FRACTION else "separate"


def case_seed(case_id: str) -> int:
    return int(hashlib.sha256(f"case:{case_id}".encode()).hexdigest()[:8], 16)
