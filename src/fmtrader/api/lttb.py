"""Largest-Triangle-Three-Buckets downsampling for equity curves."""

from __future__ import annotations

import math
from typing import Sequence


def lttb(
    xs: Sequence[float],
    ys: Sequence[float],
    threshold: int,
) -> tuple[list[float], list[float]]:
    """Downsample ``(xs, ys)`` to at most ``threshold`` points via LTTB.

    Preserves visual shape for dense series (e.g. 2M → 2000). If ``len <= threshold``,
    returns copies of the inputs.
    """
    n = len(ys)
    if n == 0:
        return [], []
    if len(xs) != n:
        raise ValueError("xs and ys must have the same length")
    if threshold < 2 or n <= threshold:
        return list(xs), list(ys)

    sampled_x: list[float] = [float(xs[0])]
    sampled_y: list[float] = [float(ys[0])]

    bucket_size = (n - 2) / (threshold - 2)
    a = 0

    for i in range(threshold - 2):
        avg_range_start = int(math.floor((i + 1) * bucket_size) + 1)
        avg_range_end = int(math.floor((i + 2) * bucket_size) + 1)
        avg_range_end = min(avg_range_end, n)

        avg_x = 0.0
        avg_y = 0.0
        avg_range_length = max(avg_range_end - avg_range_start, 1)
        for j in range(avg_range_start, avg_range_end):
            avg_x += float(xs[j])
            avg_y += float(ys[j])
        avg_x /= avg_range_length
        avg_y /= avg_range_length

        range_offs = int(math.floor(i * bucket_size) + 1)
        range_to = int(math.floor((i + 1) * bucket_size) + 1)
        range_to = min(range_to, n)

        point_ax = float(xs[a])
        point_ay = float(ys[a])
        max_area = -1.0
        next_a = range_offs
        for j in range(range_offs, range_to):
            area = (
                abs(
                    (point_ax - avg_x) * (float(ys[j]) - point_ay)
                    - (point_ax - float(xs[j])) * (avg_y - point_ay)
                )
                * 0.5
            )
            if area > max_area:
                max_area = area
                next_a = j

        sampled_x.append(float(xs[next_a]))
        sampled_y.append(float(ys[next_a]))
        a = next_a

    sampled_x.append(float(xs[n - 1]))
    sampled_y.append(float(ys[n - 1]))
    return sampled_x, sampled_y
