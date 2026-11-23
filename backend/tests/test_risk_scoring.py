"""Risk formula contracts independent of persistence and HTTP."""

from decimal import Decimal
from uuid import UUID

import pytest

from app.risk import FindingSignal, RiskScoringConfig, calculate_risk_scores
from app.risk.config import DEFAULT_DETECTOR_WEIGHTS


def _signal(
    value: int,
    *,
    detector: str = "rapid_transfers",
    category: str = "rapid_transfer_chain",
    severity: str = "medium",
    accounts: tuple[int, ...] = (100,),
    key: str | None = None,
) -> FindingSignal:
    return FindingSignal(
        finding_id=UUID(int=value),
        deduplication_key=key or f"{value:064x}",
        detector_name=detector,
        category=category,
        severity=severity,
        account_ids=tuple(UUID(int=item) for item in accounts),
    )


def test_scoring_uses_detector_category_and_severity_components():
    result = calculate_risk_scores(
        [_signal(1, severity="high")],
        RiskScoringConfig(
            detector_weights={"rapid_transfers": "0.50"},
            category_weights={"rapid_transfer_chain": "0.40"},
        ),
    )
    score = result.finding_scores[0]
    assert score.score == Decimal("0.140000")
    assert score.risk_level == "low"
    assert score.components == {
        "detector_name": "rapid_transfers",
        "category": "rapid_transfer_chain",
        "severity": "high",
        "detector_weight": "0.50",
        "category_weight": "0.40",
        "severity_contribution": "0.70",
        "finding_signal": "0.140000",
    }


def test_account_score_uses_bounded_complement_product_and_distinct_findings():
    result = calculate_risk_scores(
        [
            _signal(1, detector="one", severity="low"),
            _signal(2, detector="two", severity="medium"),
            _signal(1, detector="one", severity="low"),
        ],
        RiskScoringConfig(
            detector_weights={"one": "1", "two": "1"},
            severity_contributions={
                "info": "0",
                "low": "0.2",
                "medium": "0.4",
                "high": "0.7",
                "critical": "0.9",
            },
        ),
    )
    assert len(result.finding_scores) == 2
    assert len(result.account_scores) == 1
    assert result.account_scores[0].score == Decimal("0.520000")
    assert result.account_scores[0].risk_level == "high"
    assert len(result.account_scores[0].components) == 2


def test_score_is_deterministic_versioned_and_has_no_monetary_inputs():
    signal = _signal(1, severity="critical")
    config = RiskScoringConfig(model_version="analyst-config-2026-11")
    one = calculate_risk_scores([signal], config)
    two = calculate_risk_scores([signal], config)
    assert one == two
    assert one.model_version == "analyst-config-2026-11"
    assert one.finding_scores[0].risk_level == "critical"
    assert "amount" not in one.finding_scores[0].components
    assert "currency" not in one.finding_scores[0].components


def test_all_seven_detector_categories_have_configurable_weighted_scores():
    detector_categories = (
        ("rapid_transfers", "rapid_transfer_chain"),
        ("fan_in", "fan_in_cluster"),
        ("fan_out", "fan_out_cluster"),
        ("circular_movement", "circular_movement"),
        ("multi_hop", "multi_hop_movement"),
        ("unusual_activity", "unusual_activity"),
        ("structuring", "structuring"),
    )
    findings = [
        FindingSignal(
            finding_id=UUID(int=index + 1),
            deduplication_key=f"{index + 1:064x}",
            detector_name=detector,
            category=category,
            severity="medium",
            account_ids=(UUID(int=100 + index),),
        )
        for index, (detector, category) in enumerate(detector_categories)
    ]

    result = calculate_risk_scores(findings)
    assert len(result.finding_scores) == len(detector_categories)
    assert len(result.account_scores) == len(detector_categories)
    assert {
        score.components["detector_weight"] for score in result.finding_scores
    } == {format(weight, "f") for weight in DEFAULT_DETECTOR_WEIGHTS.values()}
    assert {score.components["category_weight"] for score in result.finding_scores} == {
        "1.00"
    }


@pytest.mark.parametrize(
    ("severity", "expected_score", "expected_level"),
    [
        ("info", "0.25", "medium"),
        ("low", "0.50", "high"),
        ("medium", "0.75", "critical"),
        ("high", "1.00", "critical"),
    ],
)
def test_adjustable_risk_band_boundaries(severity, expected_score, expected_level):
    contributions = {
        "info": "0.25",
        "low": "0.50",
        "medium": "0.75",
        "high": "1",
        "critical": "1",
    }
    result = calculate_risk_scores(
        [_signal(1, severity=severity)],
        RiskScoringConfig(
            detector_weights={"rapid_transfers": "1"},
            severity_contributions=contributions,
        ),
    )
    assert result.finding_scores[0].score == Decimal(expected_score)
    assert result.finding_scores[0].risk_level == expected_level


def test_repeated_deduplication_key_is_counted_once_and_conflicts_rejected():
    finding = _signal(1, severity="high")
    repeated = calculate_risk_scores([finding, finding])
    assert len(repeated.finding_scores) == 1
    assert len(repeated.account_scores[0].components) == 1

    conflicting = _signal(2, severity="critical", key=finding.deduplication_key)
    with pytest.raises(ValueError, match="conflicting"):
        calculate_risk_scores([finding, conflicting])


def test_configuration_rejects_out_of_range_or_incomplete_weights():
    with pytest.raises(ValueError):
        RiskScoringConfig(detector_weights={"rapid_transfers": "1.01"})
    with pytest.raises(ValueError, match="every severity"):
        RiskScoringConfig(severity_contributions={"low": "0.2"})
    with pytest.raises(ValueError, match="strictly increasing"):
        RiskScoringConfig(
            low_upper_bound=Decimal("0.6"),
            medium_upper_bound=Decimal("0.5"),
        )
