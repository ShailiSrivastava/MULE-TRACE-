"""Pure deterministic finding- and account-level score calculation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.detection.models import DetectorSeverity
from app.risk.config import RiskScoringConfig

SCORE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class FindingSignal:
    finding_id: UUID
    deduplication_key: str
    detector_name: str
    category: str
    severity: DetectorSeverity
    account_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class FindingRiskScore:
    finding_id: UUID
    deduplication_key: str
    score: Decimal
    risk_level: str
    components: dict[str, str]


@dataclass(frozen=True, slots=True)
class AccountRiskScore:
    account_id: UUID
    score: Decimal
    risk_level: str
    components: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class RiskScoringResult:
    model_version: str
    finding_scores: tuple[FindingRiskScore, ...]
    account_scores: tuple[AccountRiskScore, ...]


def _score_components(
    finding: FindingSignal, config: RiskScoringConfig
) -> dict[str, str]:
    severity_contribution = config.severity_contributions.get(finding.severity)
    if severity_contribution is None:
        raise ValueError("Scoring configuration has no contribution for this severity.")
    detector_weight = config.detector_weights.get(
        finding.detector_name, config.default_detector_weight
    )
    category_weight = config.category_weights.get(
        finding.category, config.default_category_weight
    )
    raw_signal = detector_weight * category_weight * severity_contribution
    return {
        "detector_name": finding.detector_name,
        "category": finding.category,
        "severity": finding.severity,
        "detector_weight": format(detector_weight, "f"),
        "category_weight": format(category_weight, "f"),
        "severity_contribution": format(severity_contribution, "f"),
        "finding_signal": format(raw_signal, "f"),
    }


def _risk_level(score: Decimal, config: RiskScoringConfig) -> str:
    if score < config.low_upper_bound:
        return "low"
    if score < config.medium_upper_bound:
        return "medium"
    if score < config.high_upper_bound:
        return "high"
    return "critical"


def _normalize_signal(signal: Decimal) -> Decimal:
    return signal.quantize(SCORE_QUANTUM)


def _combine_signals(
    signals: list[tuple[str, Decimal, dict[str, str]]]
) -> Decimal:
    """Combine distinct signals with a bounded complement-product formula."""

    remaining = Decimal(1)
    for _, signal, _ in sorted(signals, key=lambda item: item[0]):
        remaining *= Decimal(1) - signal
    return (Decimal(1) - remaining).quantize(SCORE_QUANTUM)


def calculate_risk_scores(
    findings: list[FindingSignal] | tuple[FindingSignal, ...],
    config: RiskScoringConfig | None = None,
) -> RiskScoringResult:
    """Score unique findings and accounts with deterministic normalized values.

    A finding signal is detector weight × category weight × severity
    contribution. Account scores combine distinct associated finding signals as
    ``1 - product(1 - signal)``. Duplicate deduplication keys count once.
    """

    settings = config or RiskScoringConfig()
    unique_findings: dict[str, FindingSignal] = {}
    for finding in findings:
        previous = unique_findings.get(finding.deduplication_key)
        if previous is not None and previous != finding:
            raise ValueError("One deduplication key maps to conflicting finding inputs.")
        unique_findings[finding.deduplication_key] = finding

    finding_scores: list[FindingRiskScore] = []
    account_signals: dict[UUID, list[tuple[str, Decimal, dict[str, str]]]] = {}
    for finding in sorted(
        unique_findings.values(), key=lambda item: (item.deduplication_key, str(item.finding_id))
    ):
        components = _score_components(finding, settings)
        signal = Decimal(components["finding_signal"])
        score = _normalize_signal(signal)
        finding_scores.append(
            FindingRiskScore(
                finding_id=finding.finding_id,
                deduplication_key=finding.deduplication_key,
                score=score,
                risk_level=_risk_level(score, settings),
                components=components,
            )
        )
        for account_id in set(finding.account_ids):
            account_signals.setdefault(account_id, []).append(
                (finding.deduplication_key, signal, components)
            )

    account_scores = [
        AccountRiskScore(
            account_id=account_id,
            score=score,
            risk_level=_risk_level(score, settings),
            components=tuple(
                {
                    "deduplication_key": key,
                    **finding_components,
                }
                for key, _, finding_components in sorted(
                    signals, key=lambda item: item[0]
                )
            ),
        )
        for account_id, signals in sorted(account_signals.items(), key=lambda item: str(item[0]))
        for score in (_combine_signals(signals),)
    ]
    return RiskScoringResult(
        model_version=settings.model_version,
        finding_scores=tuple(finding_scores),
        account_scores=tuple(account_scores),
    )
