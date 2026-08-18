"""Duration distribution shared by the director and the narration stage."""

from __future__ import annotations


def distribute_durations(
    weights: list[float],
    total: float,
    *,
    min_each: float,
    max_each: float,
    decimals: int = 3,
) -> list[float]:
    """Split ``total`` seconds across ``weights`` while respecting per-item bounds.

    Used twice: the director turns narration length into planned scene
    durations, and the narration stage rescales those to the real TTS audio
    length so picture and voice stay locked.

    Raises ``ValueError`` when the bounds cannot contain ``total``.
    """
    count = len(weights)
    if count == 0:
        raise ValueError("cannot distribute duration across zero items")
    if total <= 0:
        raise ValueError("total duration must be positive")
    if min_each * count > total + 1e-6:
        raise ValueError(f"{count} items x min {min_each}s exceeds the {total}s budget")
    if max_each * count < total - 1e-6:
        raise ValueError(f"{count} items x max {max_each}s cannot fill the {total}s budget")

    safe = [max(float(w), 1e-6) for w in weights]
    weight_sum = sum(safe)
    values = [total * w / weight_sum for w in safe]

    # Clamp, then push the resulting surplus or deficit onto the items that
    # still have headroom. A handful of passes is enough to converge.
    for _ in range(64):
        clamped = [min(max(v, min_each), max_each) for v in values]
        drift = total - sum(clamped)
        if abs(drift) < 1e-9:
            values = clamped
            break
        headroom = [max_each - v for v in clamped] if drift > 0 else [v - min_each for v in clamped]
        available = sum(headroom)
        if available < 1e-9:
            values = clamped
            break
        sign = 1.0 if drift > 0 else -1.0
        values = [
            v + sign * abs(drift) * (h / available) for v, h in zip(clamped, headroom, strict=True)
        ]
    else:  # pragma: no cover - the loop converges long before 64 passes
        values = [min(max(v, min_each), max_each) for v in values]

    rounded = [round(v, decimals) for v in values]
    # Rounding leaves a few milliseconds on the table; give them to the item
    # with the most slack so the sum matches ``total`` exactly.
    residual = round(total - sum(rounded), decimals)
    if abs(residual) >= 10**-decimals:
        index = max(
            range(count),
            key=lambda i: (max_each - rounded[i]) if residual > 0 else (rounded[i] - min_each),
        )
        rounded[index] = round(rounded[index] + residual, decimals)
    return rounded
