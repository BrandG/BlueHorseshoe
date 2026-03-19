"""
Signature extraction from segmented price series.

Converts a Segmentation into a fixed-length numeric vector and a compact
motif key string for exact-match catalog lookup.
"""

from dataclasses import dataclass
from typing import Tuple

from bluehorseshoe.analysis.curves.segmenter import Segment, Segmentation


# Bucket thresholds
_MAG_THRESHOLDS = (0.5, 1.5, 3.0, 5.0)  # → 0-4
_DUR_THRESHOLDS = (5, 10)                # → 0-2
_SLOPE_THRESHOLDS = (0.1, 0.3)           # → 0-2
_CURV_THRESHOLDS = (0.3, 0.8)            # → 0-2

# Motif key labels
_DIR_LABELS = {1: 'U', -1: 'D'}
_DUR_LABELS = {0: 'S', 1: 'M', 2: 'L'}


def _bucket(value: float, thresholds: tuple) -> int:
    """Assign value to a bucket based on thresholds."""
    for i, t in enumerate(thresholds):
        if value < t:
            return i
    return len(thresholds)


def _segment_descriptors(seg: Segment) -> Tuple[int, int, int, int, int]:
    """Extract 5 bucketed descriptors from a segment."""
    direction = seg.direction  # +1 or -1
    mag_bucket = _bucket(seg.magnitude, _MAG_THRESHOLDS)
    dur_bucket = _bucket(seg.duration, _DUR_THRESHOLDS)
    slope_bucket = _bucket(seg.slope, _SLOPE_THRESHOLDS)
    curv_bucket = _bucket(seg.curvature, _CURV_THRESHOLDS)
    return (direction, mag_bucket, dur_bucket, slope_bucket, curv_bucket)


def _neutral_descriptors() -> Tuple[int, int, int, int, int]:
    """Neutral segment descriptors for padding."""
    return (1, 0, 1, 1, 0)  # up, tiny, medium, moderate, straight


def _segment_to_motif_token(direction: int, mag_bucket: int, dur_bucket: int) -> str:
    """Convert segment descriptors to a motif key token like 'U3M'."""
    d = _DIR_LABELS.get(direction, 'U')
    dur = _DUR_LABELS.get(dur_bucket, 'M')
    return f"{d}{mag_bucket}{dur}"


@dataclass(frozen=True)
class CurveSignature:
    """Fixed-length representation of a price curve's recent shape."""
    vector: Tuple[float, ...]   # 17 elements, hashable
    motif_key: str              # e.g. "U3M:D1S:U2L"
    window_size: int
    segment_count: int          # actual segments available (may be <3)
    raw_segments: Tuple[Segment, ...]


def extract_signature(
    segmentation: Segmentation, n_segments: int = 3
) -> CurveSignature:
    """
    Extract a CurveSignature from a Segmentation.

    Uses the last `n_segments` segments. Pads with neutral segments
    if fewer are available.

    Args:
        segmentation: The segmentation result.
        n_segments: Number of trailing segments to use (default 3).

    Returns:
        CurveSignature with 17-dim vector and motif key.
    """
    segments = segmentation.segments
    actual_count = len(segments)

    # Take last n_segments (or pad)
    if actual_count >= n_segments:
        used = segments[-n_segments:]
    else:
        used = segments[:]

    # Extract descriptors for each segment
    all_descriptors = []
    motif_tokens = []

    for seg in used:
        desc = _segment_descriptors(seg)
        all_descriptors.append(desc)
        motif_tokens.append(_segment_to_motif_token(desc[0], desc[1], desc[2]))

    # Pad if needed
    while len(all_descriptors) < n_segments:
        desc = _neutral_descriptors()
        all_descriptors.insert(0, desc)  # pad at front (oldest position)
        motif_tokens.insert(0, _segment_to_motif_token(desc[0], desc[1], desc[2]))

    # Build 15-dim vector from segment descriptors
    vec_parts = []
    for desc in all_descriptors:
        vec_parts.extend([float(d) for d in desc])

    # Global features
    if segmentation.turning_points:
        norm_prices = [tp.norm_price for tp in segmentation.turning_points]
        total_range = max(norm_prices) - min(norm_prices)

        # Net displacement vs total path length
        net_disp = abs(norm_prices[-1] - norm_prices[0])
        total_path = sum(abs(norm_prices[i + 1] - norm_prices[i])
                         for i in range(len(norm_prices) - 1))
        net_direction = net_disp / total_path if total_path > 0 else 0.0
    else:
        total_range = 0.0
        net_direction = 0.0

    vec_parts.append(float(total_range))
    vec_parts.append(float(net_direction))

    motif_key = ":".join(motif_tokens)

    return CurveSignature(
        vector=tuple(vec_parts),
        motif_key=motif_key,
        window_size=segmentation.window_size,
        segment_count=actual_count,
        raw_segments=tuple(used)
    )


def signatures_similar(
    a: CurveSignature, b: CurveSignature, max_hamming: int = 3
) -> bool:
    """
    Check if two signatures are similar via Hamming distance on bucketed dims.

    Compares the first 15 dimensions (3×5 bucketed descriptors) only.
    """
    if len(a.vector) < 15 or len(b.vector) < 15:
        return False

    hamming = sum(1 for i in range(15) if a.vector[i] != b.vector[i])
    return hamming <= max_hamming
