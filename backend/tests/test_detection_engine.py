"""Unit coverage for pure, in-memory Phase 8 detectors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.detection.base import DetectorOutput
from app.detection.circular_movement import CircularMovementDetector
from app.detection.config import (
    CircularMovementConfig,
    DetectionConfig,
    FanInConfig,
    FanOutConfig,
    MultiHopConfig,
    RapidTransfersConfig,
    StructuringConfig,
    UnusualActivityConfig,
)
from app.detection.fan_in_out import FanInDetector, FanOutDetector
from app.detection.models import create_finding
from app.detection.multi_hop import MultiHopDetector
from app.detection.orchestrator import DetectionOrchestrator, run_detection
from app.detection.rapid_transfers import RapidTransferDetector
from app.detection.structuring import StructuringDetector
from app.detection.unusual_activity import UnusualActivityDetector
from app.graph.builder import build_transaction_graph
from app.graph.models import AccountRecord, TransactionRecord

DATASET_ID = UUID(int=9000)
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _account(account_id: int) -> AccountRecord:
    return AccountRecord(id=UUID(int=account_id), dataset_id=DATASET_ID)


def _tx(
    transaction_id: int,
    sender: int,
    receiver: int,
    *,
    amount: str = "10.00",
    currency: str = "USD",
    seconds: int = 0,
    occurred_at: datetime | None = None,
) -> TransactionRecord:
    return TransactionRecord(
        id=UUID(int=transaction_id),
        dataset_id=DATASET_ID,
        sender_account_id=UUID(int=sender),
        receiver_account_id=UUID(int=receiver),
        amount=Decimal(amount),
        currency=currency,
        occurred_at=occurred_at or BASE + timedelta(seconds=seconds),
    )


def _graph(*transactions: TransactionRecord, account_ids: tuple[int, ...] = ()):
    ids = set(account_ids)
    for transaction in transactions:
        ids.add(transaction.sender_account_id.int)
        ids.add(transaction.receiver_account_id.int)
    return build_transaction_graph(
        DATASET_ID,
        [_account(account_id) for account_id in sorted(ids)],
        transactions,
    )


def _detect(detector, graph, config):
    return detector.detect(graph, dataset_id=DATASET_ID, config=config)


def test_rapid_transfer_chain_is_continuous_bounded_and_transaction_level():
    first = _tx(1, 1, 2, seconds=0)
    parallel = _tx(2, 1, 2, seconds=1)
    second = _tx(3, 2, 3, seconds=2)
    output = _detect(
        RapidTransferDetector(),
        _graph(first, parallel, second),
        RapidTransfersConfig(
            minimum_transaction_count=2,
            minimum_distinct_accounts=3,
            maximum_elapsed_seconds=60,
            maximum_path_length=2,
        ),
    )
    assert len(output.findings) == 2
    assert {finding.transaction_ids for finding in output.findings} == {
        (first.id, second.id),
        (parallel.id, second.id),
    }
    assert all(finding.evidence["elapsed_seconds"] <= 2 for finding in output.findings)


def test_rapid_transfers_reject_disconnected_and_out_of_window_sequences():
    disconnected = _graph(
        _tx(1, 1, 2, seconds=0),
        _tx(2, 1, 3, seconds=1),
        _tx(3, 1, 4, seconds=2),
    )
    outside_window = _graph(
        _tx(4, 1, 2, seconds=0),
        _tx(5, 2, 3, seconds=61),
    )
    settings = RapidTransfersConfig(
        minimum_transaction_count=2,
        minimum_distinct_accounts=3,
        maximum_elapsed_seconds=60,
        maximum_path_length=2,
    )
    assert not _detect(RapidTransferDetector(), disconnected, settings).findings
    assert not _detect(RapidTransferDetector(), outside_window, settings).findings


def test_rapid_transfer_limits_and_minimum_count_are_enforced():
    graph = _graph(
        _tx(1, 1, 2),
        _tx(2, 2, 3, seconds=1),
        _tx(3, 3, 4, seconds=2),
    )
    output = _detect(
        RapidTransferDetector(),
        graph,
        RapidTransfersConfig(
            minimum_transaction_count=2,
            minimum_distinct_accounts=3,
            maximum_path_length=2,
        ),
    )
    assert output.findings
    assert all(len(finding.transaction_ids) <= 2 for finding in output.findings)
    with pytest.raises(ValueError, match="cannot exceed"):
        RapidTransfersConfig(minimum_transaction_count=4, maximum_path_length=3)


def test_rapid_transfer_edge_expansion_limit_is_reported():
    graph = _graph(_tx(1, 1, 2), _tx(2, 2, 3, seconds=1))
    output = _detect(
        RapidTransferDetector(),
        graph,
        RapidTransfersConfig(
            minimum_transaction_count=2,
            minimum_distinct_accounts=3,
            maximum_path_length=2,
            max_edge_expansions=1,
        ),
    )
    assert output.statistics["truncated"] is True


def test_fan_in_counts_unique_senders_separately_from_parallel_edges():
    transactions = (
        _tx(1, 1, 9),
        _tx(2, 1, 9, seconds=1),
        _tx(3, 2, 9, seconds=2),
        _tx(4, 3, 9, seconds=3),
    )
    output = _detect(
        FanInDetector(),
        _graph(*transactions),
        FanInConfig(
            minimum_unique_senders=3,
            minimum_incoming_transactions=4,
            window_seconds=60,
        ),
    )
    assert len(output.findings) == 1
    finding = output.findings[0]
    assert finding.evidence["unique_counterparty_count"] == 3
    assert finding.evidence["transaction_count"] == 4
    assert set(finding.transaction_ids) == {item.id for item in transactions}


def test_fan_out_currency_thresholds_are_never_combined():
    graph = _graph(
        _tx(1, 9, 1, amount="40", currency="USD"),
        _tx(2, 9, 2, amount="40", currency="EUR", seconds=1),
    )
    output = _detect(
        FanOutDetector(),
        graph,
        FanOutConfig(
            minimum_unique_receivers=2,
            minimum_outgoing_transactions=2,
            minimum_total_amount_by_currency={"USD": "70", "EUR": "60"},
            window_seconds=60,
        ),
    )
    assert not output.findings


def test_fan_in_uses_half_open_window_boundary():
    graph = _graph(
        _tx(1, 1, 9, seconds=0),
        _tx(2, 2, 9, seconds=60),
    )
    output = _detect(
        FanInDetector(),
        graph,
        FanInConfig(
            minimum_unique_senders=2,
            minimum_incoming_transactions=2,
            window_seconds=60,
        ),
    )
    assert not output.findings


def test_fan_out_detects_many_distinct_receivers_in_one_window():
    graph = _graph(
        _tx(1, 9, 1),
        _tx(2, 9, 2, seconds=10),
        _tx(3, 9, 3, seconds=20),
    )
    output = _detect(
        FanOutDetector(),
        graph,
        FanOutConfig(
            minimum_unique_receivers=3,
            minimum_outgoing_transactions=3,
            window_seconds=60,
        ),
    )
    assert len(output.findings) == 1
    assert output.findings[0].evidence["direction"] == "outgoing"


def test_circular_movement_finds_triangle_and_keeps_parallel_edge_evidence():
    transactions = (
        _tx(1, 1, 2),
        _tx(2, 1, 2, seconds=1),
        _tx(3, 2, 3, seconds=2),
        _tx(4, 3, 1, seconds=3),
    )
    output = _detect(
        CircularMovementDetector(),
        _graph(*transactions),
        CircularMovementConfig(time_window_seconds=60, maximum_cycles=10),
    )
    assert len(output.findings) == 2
    assert all(len(finding.account_ids) == 3 for finding in output.findings)
    assert all(len(finding.transaction_ids) == 3 for finding in output.findings)
    assert len({finding.deduplication_key for finding in output.findings}) == 2


def test_circular_movement_handles_longer_cycles_acyclic_edges_and_self_loops():
    cycle = _graph(
        _tx(1, 1, 2),
        _tx(2, 2, 3, seconds=1),
        _tx(3, 3, 4, seconds=2),
        _tx(4, 4, 1, seconds=3),
        _tx(5, 5, 6),
        _tx(6, 7, 7),
    )
    output = _detect(
        CircularMovementDetector(),
        cycle,
        CircularMovementConfig(
            minimum_cycle_length=3,
            maximum_cycle_length=4,
            time_window_seconds=60,
        ),
    )
    assert len(output.findings) == 1
    assert output.findings[0].evidence["cycle_length"] == 4


def test_circular_movement_enforces_time_and_enumeration_limits():
    expired = _graph(
        _tx(1, 1, 2, seconds=0),
        _tx(2, 2, 3, seconds=30),
        _tx(3, 3, 1, seconds=60),
    )
    assert not _detect(
        CircularMovementDetector(),
        expired,
        CircularMovementConfig(time_window_seconds=60),
    ).findings

    parallel_cycle = _graph(
        _tx(4, 1, 2),
        _tx(5, 1, 2, seconds=1),
        _tx(6, 2, 3, seconds=2),
        _tx(7, 3, 1, seconds=3),
    )
    bounded = _detect(
        CircularMovementDetector(),
        parallel_cycle,
        CircularMovementConfig(time_window_seconds=60, maximum_cycles=1),
    )
    assert len(bounded.findings) == 1
    assert bounded.statistics["truncated"] is True


def test_multi_hop_reuses_graph_paths_and_excludes_direct_movements():
    first = _tx(1, 1, 2, seconds=0)
    parallel = _tx(2, 1, 2, seconds=1)
    second = _tx(3, 2, 3, seconds=2)
    direct = _tx(4, 1, 3, seconds=3)
    graph = _graph(first, parallel, second, direct)
    output = _detect(
        MultiHopDetector(),
        graph,
        MultiHopConfig(time_window_seconds=60, maximum_hops=2),
    )
    pair_findings = [
        finding
        for finding in output.findings
        if finding.account_ids[0] == UUID(int=1)
        and finding.account_ids[-1] == UUID(int=3)
    ]
    assert len(pair_findings) == 2
    assert all(direct.id not in finding.transaction_ids for finding in pair_findings)
    assert {finding.transaction_ids for finding in pair_findings} == {
        (first.id, second.id),
        (parallel.id, second.id),
    }


def test_multi_hop_ignores_unreachable_nonchronological_and_overlong_paths():
    nonchronological = _graph(
        _tx(1, 1, 2, seconds=10),
        _tx(2, 2, 3, seconds=1),
        account_ids=(4, 5),
    )
    assert not _detect(
        MultiHopDetector(),
        nonchronological,
        MultiHopConfig(time_window_seconds=60, maximum_hops=2),
    ).findings
    too_long = _graph(
        _tx(3, 1, 2),
        _tx(4, 2, 3, seconds=1),
        _tx(5, 3, 4, seconds=2),
    )
    result = _detect(
        MultiHopDetector(),
        too_long,
        MultiHopConfig(time_window_seconds=60, maximum_hops=2),
    )
    assert all(finding.evidence["hop_count"] <= 2 for finding in result.findings)
    assert not any(
        finding.account_ids == (UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4))
        for finding in result.findings
    )


def test_multi_hop_expansion_cap_is_reported():
    graph = _graph(
        _tx(1, 1, 2),
        _tx(2, 2, 3, seconds=1),
        _tx(3, 1, 3, seconds=2),
    )
    result = _detect(
        MultiHopDetector(),
        graph,
        MultiHopConfig(
            time_window_seconds=60,
            maximum_hops=2,
            maximum_expansions_per_pair=1,
            maximum_total_expansions=1,
        ),
    )
    assert result.statistics["truncated"] is True


def _unusual_config() -> UnusualActivityConfig:
    return UnusualActivityConfig(
        activity_window_seconds=86_400,
        baseline_periods=2,
        minimum_baseline_periods=2,
        minimum_baseline_transactions=2,
        minimum_observed_transactions=3,
        minimum_amount_baseline_transactions=2,
    )


def _history_graph(*observed_amounts: tuple[str, str] | str):
    transactions = [
        _tx(1, 1, 6, amount="5", occurred_at=BASE + timedelta(hours=13)),
        _tx(2, 1, 2, amount="10", occurred_at=BASE + timedelta(days=1, hours=13)),
        _tx(
            3,
            1,
            3,
            amount="1000",
            currency="EUR",
            occurred_at=BASE + timedelta(days=1, hours=13, minutes=1),
        ),
        _tx(4, 1, 4, amount="20", occurred_at=BASE + timedelta(days=2, hours=13)),
        _tx(
            5,
            1,
            5,
            amount="1100",
            currency="EUR",
            occurred_at=BASE + timedelta(days=2, hours=13, minutes=1),
        ),
    ]
    for index, observed_amount in enumerate(observed_amounts, start=6):
        amount, currency = (
            observed_amount
            if isinstance(observed_amount, tuple)
            else (observed_amount, "USD")
        )
        transactions.append(
            _tx(
                index,
                1,
                10 + index,
                amount=amount,
                currency=currency,
                occurred_at=BASE + timedelta(days=4, hours=12, seconds=index),
            )
        )
    return _graph(*transactions)


def test_unusual_activity_detects_frequency_and_per_currency_amount_deviations():
    graph = _history_graph("100", "100", ("2000", "EUR"), ("2000", "EUR"))
    output = _detect(UnusualActivityDetector(), graph, _unusual_config())
    categories = {finding.category for finding in output.findings}
    assert "unusual_transaction_frequency" in categories
    amount_findings = [
        finding
        for finding in output.findings
        if finding.category == "unusual_transaction_amount"
    ]
    assert {finding.evidence["currency"] for finding in amount_findings} == {
        "USD",
        "EUR",
    }
    assert all(
        finding.evidence["comparison_threshold"]
        == ("32.5" if finding.evidence["currency"] == "USD" else "1225.0")
        for finding in amount_findings
    )


def test_unusual_activity_reports_insufficient_history_without_guessing():
    graph = _graph(_tx(1, 1, 2, seconds=10))
    output = _detect(UnusualActivityDetector(), graph, _unusual_config())
    assert not output.findings
    assert output.statistics["insufficient_history_accounts"] > 0


def test_unusual_activity_does_not_flag_stable_frequency_or_amounts():
    transactions = []
    for day, first_id in ((2, 1), (3, 3)):
        transactions.extend(
            [
                _tx(
                    first_id,
                    1,
                    first_id + 10,
                    amount="10",
                    occurred_at=BASE + timedelta(days=day, hours=10),
                ),
                _tx(
                    first_id + 1,
                    1,
                    first_id + 11,
                    amount="10",
                    occurred_at=BASE + timedelta(days=day, hours=11),
                ),
            ]
        )
    transactions.append(
        _tx(5, 1, 20, amount="10", occurred_at=BASE + timedelta(days=4, hours=10))
    )
    output = _detect(
        UnusualActivityDetector(), _graph(*transactions), _unusual_config()
    )
    assert not output.findings


def test_unusual_frequency_uses_each_accounts_own_activity_level():
    transactions = [_tx(1, 90, 91, occurred_at=BASE + timedelta(hours=12))]
    transaction_id = 2
    for day in (1, 2):
        for _ in range(2):
            transactions.append(
                _tx(
                    transaction_id,
                    1,
                    100 + transaction_id,
                    occurred_at=BASE
                    + timedelta(days=day, hours=15, seconds=transaction_id),
                )
            )
            transaction_id += 1
        transactions.append(
            _tx(
                transaction_id,
                20,
                100 + transaction_id,
                occurred_at=BASE
                + timedelta(days=day, hours=15, seconds=transaction_id),
            )
        )
        transaction_id += 1
    for sender, count in ((1, 2), (20, 3)):
        for _ in range(count):
            transactions.append(
                _tx(
                    transaction_id,
                    sender,
                    100 + transaction_id,
                    occurred_at=BASE
                    + timedelta(days=4, hours=13, seconds=transaction_id),
                )
            )
            transaction_id += 1

    config = UnusualActivityConfig(
        baseline_periods=2,
        minimum_baseline_periods=2,
        minimum_baseline_transactions=2,
        minimum_observed_transactions=3,
        minimum_amount_baseline_transactions=100,
    )
    output = _detect(UnusualActivityDetector(), _graph(*transactions), config)
    frequency_findings = [
        finding
        for finding in output.findings
        if finding.category == "unusual_transaction_frequency"
    ]
    assert [finding.account_ids for finding in frequency_findings] == [(UUID(int=20),)]


def test_structuring_uses_inclusive_bands_and_half_open_time_windows():
    graph = _graph(
        _tx(1, 1, 2, amount="10", seconds=0),
        _tx(2, 1, 3, amount="15", seconds=10),
        _tx(3, 1, 4, amount="20", seconds=20),
    )
    output = _detect(
        StructuringDetector(),
        graph,
        StructuringConfig(
            window_seconds=60,
            minimum_transaction_count=3,
            threshold_bands_by_currency={
                "usd": [{"minimum_amount": "10", "maximum_amount": "20"}]
            },
        ),
    )
    assert len(output.findings) == 1
    assert set(output.findings[0].transaction_ids) == {
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
    }
    assert output.findings[0].evidence["configured_band"] == {
        "minimum_amount_inclusive": "10",
        "maximum_amount_inclusive": "20",
    }

    boundary_graph = _graph(
        _tx(4, 1, 5, amount="15", seconds=0),
        _tx(5, 1, 6, amount="15", seconds=60),
    )
    boundary_output = _detect(
        StructuringDetector(),
        boundary_graph,
        StructuringConfig(
            window_seconds=60,
            minimum_transaction_count=2,
            threshold_bands_by_currency={
                "USD": [{"minimum_amount": "10", "maximum_amount": "20"}]
            },
        ),
    )
    assert not boundary_output.findings


def test_structuring_is_per_currency_and_requires_configured_thresholds():
    graph = _graph(
        _tx(1, 1, 2, amount="10", currency="USD"),
        _tx(2, 1, 3, amount="10", currency="EUR", seconds=1),
        _tx(3, 1, 4, amount="10", currency="USD", seconds=2),
    )
    default_output = _detect(StructuringDetector(), graph, StructuringConfig())
    assert not default_output.findings
    configured = _detect(
        StructuringDetector(),
        graph,
        StructuringConfig(
            minimum_transaction_count=2,
            threshold_bands_by_currency={
                "USD": [{"minimum_amount": "10", "maximum_amount": "10"}],
                "EUR": [{"minimum_amount": "10", "maximum_amount": "10"}],
            },
        ),
    )
    assert {finding.evidence["currency"] for finding in configured.findings} == {"USD"}


def test_structuring_can_require_multiple_active_utc_days():
    graph = _graph(
        _tx(1, 1, 2, amount="10", occurred_at=BASE + timedelta(days=1, hours=23)),
        _tx(2, 1, 3, amount="10", occurred_at=BASE + timedelta(days=2, hours=1)),
    )
    output = _detect(
        StructuringDetector(),
        graph,
        StructuringConfig(
            window_seconds=172_800,
            minimum_transaction_count=2,
            minimum_active_days=2,
            threshold_bands_by_currency={
                "USD": [{"minimum_amount": "10", "maximum_amount": "10"}]
            },
        ),
    )
    assert len(output.findings) == 1
    assert len(output.findings[0].evidence["active_utc_days"]) == 2


def test_detection_configuration_rejects_float_money_and_overlapping_bands():
    with pytest.raises(ValueError, match="finite decimals"):
        StructuringConfig(
            threshold_bands_by_currency={
                "USD": [{"minimum_amount": 1.2, "maximum_amount": "2"}]
            }
        )
    with pytest.raises(ValueError, match="cannot overlap"):
        StructuringConfig(
            threshold_bands_by_currency={
                "USD": [
                    {"minimum_amount": "1", "maximum_amount": "2"},
                    {"minimum_amount": "2", "maximum_amount": "3"},
                ]
            }
        )


def test_orchestrator_handles_empty_graph_disabled_detectors_and_stable_order():
    graph = _graph(account_ids=(1, 2))
    config = DetectionConfig(fan_in=FanInConfig(enabled=False))
    first = run_detection(graph, config)
    second = run_detection(graph, config)
    assert first == second
    assert first.findings == ()
    assert len(first.executions) == 7
    assert (
        next(item for item in first.executions if item.detector_name == "fan_in").state
        == "disabled"
    )
    assert all(
        item.state == "succeeded"
        for item in first.executions
        if item.detector_name != "fan_in"
    )


class _DuplicateDetector:
    name = "duplicate_test"
    config_key = "rapid_transfers"
    version = "test-1"

    def __init__(self, finding):
        self.finding = finding

    def detect(self, graph, *, dataset_id, config):
        return DetectorOutput((self.finding, self.finding), {"raw_count": 2})


class _FailingDetector:
    name = "failure_test"
    config_key = "fan_in"
    version = "test-1"

    def detect(self, graph, *, dataset_id, config):
        raise RuntimeError("sensitive transaction detail")


def test_orchestrator_isolates_failures_deduplicates_and_withholds_exception_details():
    graph = _graph(_tx(1, 1, 2))
    finding = create_finding(
        detector_name="duplicate_test",
        detector_version="test-1",
        category="test_indicator",
        severity="low",
        title="Test indicator",
        explanation="A deterministic test finding.",
        dataset_id=DATASET_ID,
        account_ids=(UUID(int=1), UUID(int=2)),
        transaction_ids=(UUID(int=1),),
        start_at=BASE,
        end_at=BASE,
        evidence={"transaction_count": 1},
        parameters={},
    )
    result = DetectionOrchestrator(
        (_DuplicateDetector(finding), _FailingDetector())
    ).run(graph, DetectionConfig())
    assert len(result.findings) == 1
    assert result.executions[0].finding_count == 1
    assert result.executions[0].state == "succeeded"
    assert result.executions[1].state == "failed"
    assert (
        result.executions[1].message == "Detector execution failed; details withheld."
    )
    assert "sensitive transaction detail" not in result.model_dump_json()


def test_orchestrator_rejects_dataset_scope_mismatch_and_omits_graph_metadata():
    graph = _graph(_tx(1, 1, 2))
    graph.nodes[UUID(int=1)]["ground_truth_labels"] = ["synthetic_mule"]
    graph.nodes[UUID(int=1)]["metadata_json"] = {"private": "sensitive"}
    with pytest.raises(ValueError, match="does not match"):
        run_detection(graph, dataset_id=UUID(int=9999))

    graph = _graph(_tx(1, 1, 2, seconds=0), _tx(2, 2, 3, seconds=1))
    graph.edges[UUID(int=1), UUID(int=2), UUID(int=1)]["ground_truth_labels"] = [
        "synthetic_mule"
    ]
    graph.edges[UUID(int=1), UUID(int=2), UUID(int=1)]["metadata_json"] = {
        "private": "sensitive"
    }
    result = run_detection(
        graph,
        DetectionConfig(
            rapid_transfers=RapidTransfersConfig(
                minimum_transaction_count=2,
                minimum_distinct_accounts=3,
                maximum_path_length=2,
            )
        ),
    )
    encoded = result.model_dump_json()
    assert "synthetic_mule" not in encoded
    assert "sensitive" not in encoded


def test_finding_identity_is_stable_and_timestamp_offsets_normalize_to_utc():
    offset_time = datetime.fromisoformat("2026-01-01T05:30:00+05:30")
    one = create_finding(
        detector_name="stable",
        detector_version="1",
        category="test",
        severity="low",
        title="Stable",
        explanation="Same input.",
        dataset_id=DATASET_ID,
        account_ids=(UUID(int=1),),
        transaction_ids=(UUID(int=2),),
        start_at=offset_time,
        end_at=offset_time,
        evidence={},
        parameters={},
    )
    two = create_finding(
        detector_name="stable",
        detector_version="1",
        category="test",
        severity="low",
        title="Stable",
        explanation="Same input.",
        dataset_id=DATASET_ID,
        account_ids=(UUID(int=1),),
        transaction_ids=(UUID(int=2),),
        start_at=BASE,
        end_at=BASE,
        evidence={},
        parameters={},
    )
    assert one.finding_id == two.finding_id
    assert one.deduplication_key == two.deduplication_key
    assert one.time_window.start_at == BASE
