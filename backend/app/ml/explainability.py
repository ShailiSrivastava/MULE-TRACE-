"""Deterministic descriptive deviations from the fitted feature baseline."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from app.ml.contracts import FeatureVector


@dataclass(frozen=True, slots=True)
class FeatureBaseline:
    medians: dict[str, Decimal]
    scales: dict[str, Decimal]


def build_feature_baseline(
    training_vectors: tuple[FeatureVector, ...] | list[FeatureVector],
) -> FeatureBaseline:
    """Keep only robust per-column summary statistics, not training rows."""

    names = sorted({name for vector in training_vectors for name in vector.features})
    medians: dict[str, Decimal] = {}
    scales: dict[str, Decimal] = {}
    for name in names:
        values = [
            Decimal(value)
            for vector in training_vectors
            if (value := vector.features.get(name)) is not None
        ]
        if not values:
            continue
        center = median(values)
        mad = median([abs(value - center) for value in values])
        if mad > 0:
            scale = mad * Decimal("1.4826")
        elif len(values) > 1:
            variance = sum(((value - center) ** 2 for value in values), Decimal(0)) / Decimal(
                len(values)
            )
            scale = variance.sqrt()
        else:
            scale = Decimal(0)
        medians[name] = center
        scales[name] = scale
    return FeatureBaseline(medians=medians, scales=scales)


def explain_feature_deviations(
    vector: FeatureVector,
    baseline: FeatureBaseline,
    *,
    maximum_explanations: int = 3,
    minimum_robust_scales: Decimal = Decimal(2),
) -> tuple[str, ...]:
    """Describe only feature values that differ substantially from training.

    These are descriptive comparisons rather than causal feature attribution
    from an unsupervised estimator.
    """

    if maximum_explanations < 1:
        raise ValueError("maximum_explanations must be positive.")
    if minimum_robust_scales <= 0:
        raise ValueError("minimum_robust_scales must be positive.")
    ranked: list[tuple[Decimal, str, str]] = []
    for name, raw_value in vector.features.items():
        if raw_value is None or name not in baseline.medians:
            continue
        value = Decimal(raw_value)
        center = baseline.medians[name]
        scale = baseline.scales.get(name, Decimal(0))
        if scale == 0:
            if value == center:
                continue
            description = (
                f"{name} differs from a constant training baseline "
                f"({format(value, 'f')} vs {format(center, 'f')})."
            )
            ranked.append((Decimal("Infinity"), name, description))
            continue
        deviation = (value - center) / scale
        magnitude = abs(deviation)
        if magnitude < minimum_robust_scales:
            continue
        direction = "above" if deviation > 0 else "below"
        description = (
            f"{name} is {magnitude.quantize(Decimal('0.01'))} robust scales {direction} "
            f"the training median ({format(value, 'f')} vs {format(center, 'f')})."
        )
        ranked.append((magnitude, name, description))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[2] for item in ranked[:maximum_explanations])
