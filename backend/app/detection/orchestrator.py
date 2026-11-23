"""Deterministic, sequential orchestration for pure graph detectors."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.detection.base import Detector, graph_dataset_id
from app.detection.circular_movement import CircularMovementDetector
from app.detection.config import DetectionConfig
from app.detection.fan_in_out import FanInDetector, FanOutDetector
from app.detection.models import (
    DetectionFinding,
    DetectionRunResult,
    DetectorExecution,
)
from app.detection.multi_hop import MultiHopDetector
from app.detection.rapid_transfers import RapidTransferDetector
from app.detection.structuring import StructuringDetector
from app.detection.unusual_activity import UnusualActivityDetector
from app.graph.builder import TransactionGraph

DEFAULT_DETECTORS: tuple[Detector, ...] = (
    RapidTransferDetector(),
    FanInDetector(),
    FanOutDetector(),
    CircularMovementDetector(),
    MultiHopDetector(),
    UnusualActivityDetector(),
    StructuringDetector(),
)


def _scalar_statistics(values: dict[str, Any]) -> dict[str, int | bool | str]:
    result: dict[str, int | bool | str] = {}
    for key, value in values.items():
        if isinstance(value, bool | int | str):
            result[key] = value
        else:
            raise TypeError("Detector statistics must contain scalar JSON values.")
    return dict(sorted(result.items()))


def _finding_sort_key(finding: DetectionFinding) -> tuple[str, str, str, str, str]:
    start_at = finding.time_window.start_at.isoformat() if finding.time_window else ""
    return (
        str(finding.dataset_id or ""),
        finding.detector_name,
        finding.category,
        start_at,
        finding.deduplication_key,
    )


class DetectionOrchestrator:
    """Runs selected detectors independently and aggregates stable findings.

    Detectors execute sequentially. A detector exception is represented in its
    execution record with a generic message; exception details and transaction
    data are intentionally withheld.
    """

    def __init__(self, detectors: Sequence[Detector] = DEFAULT_DETECTORS) -> None:
        names = [detector.name for detector in detectors]
        config_keys = [detector.config_key for detector in detectors]
        if len(names) != len(set(names)) or len(config_keys) != len(set(config_keys)):
            raise ValueError("Detector names and configuration keys must be unique.")
        self.detectors = tuple(detectors)

    def run(
        self,
        graph: TransactionGraph,
        config: DetectionConfig | None = None,
        *,
        dataset_id: UUID | None = None,
    ) -> DetectionRunResult:
        settings = config or DetectionConfig()
        resolved_dataset_id = graph_dataset_id(graph, dataset_id)
        self._validate_graph_scope(graph, resolved_dataset_id)

        executions: list[DetectorExecution] = []
        findings_by_key: dict[str, DetectionFinding] = {}
        for detector in self.detectors:
            detector_config = getattr(settings, detector.config_key, None)
            if detector_config is None:
                executions.append(
                    DetectorExecution(
                        detector_name=detector.name,
                        detector_version=detector.version,
                        state="failed",
                        finding_count=0,
                        error_code="detector_configuration_missing",
                        error_type="ConfigurationError",
                        message="Detector configuration is unavailable.",
                    )
                )
                continue
            if not detector_config.enabled:
                executions.append(
                    DetectorExecution(
                        detector_name=detector.name,
                        detector_version=detector.version,
                        state="disabled",
                        finding_count=0,
                    )
                )
                continue

            try:
                output = detector.detect(
                    graph,
                    dataset_id=resolved_dataset_id,
                    config=detector_config,
                )
                safe_statistics = _scalar_statistics(output.statistics)
                accepted: dict[str, DetectionFinding] = {}
                for finding in output.findings:
                    if finding.dataset_id != resolved_dataset_id:
                        raise ValueError("Finding dataset does not match graph scope.")
                    accepted.setdefault(finding.deduplication_key, finding)
                for key, finding in accepted.items():
                    existing = findings_by_key.get(key)
                    if existing is None or json.dumps(
                        finding.model_dump(mode="json"), sort_keys=True
                    ) < json.dumps(existing.model_dump(mode="json"), sort_keys=True):
                        findings_by_key[key] = finding
                executions.append(
                    DetectorExecution(
                        detector_name=detector.name,
                        detector_version=detector.version,
                        state="succeeded",
                        finding_count=len(accepted),
                        statistics=safe_statistics,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - detectors are isolated by contract.
                executions.append(
                    DetectorExecution(
                        detector_name=detector.name,
                        detector_version=detector.version,
                        state="failed",
                        finding_count=0,
                        error_code="detector_execution_failed",
                        error_type=type(exc).__name__,
                        message="Detector execution failed; details withheld.",
                    )
                )

        return DetectionRunResult(
            dataset_id=resolved_dataset_id,
            findings=tuple(sorted(findings_by_key.values(), key=_finding_sort_key)),
            executions=tuple(executions),
        )

    @staticmethod
    def _validate_graph_scope(graph: TransactionGraph, dataset_id: UUID | None) -> None:
        if dataset_id is None:
            return
        expected = str(dataset_id)
        for _, attributes in graph.nodes(data=True):
            raw = attributes.get("dataset_id")
            if raw is not None and str(raw) != expected:
                raise ValueError("Graph contains an account outside its dataset scope.")
        for _, _, attributes in graph.edges(data=True):
            raw = attributes.get("dataset_id")
            if raw is not None and str(raw) != expected:
                raise ValueError(
                    "Graph contains a transaction outside its dataset scope."
                )


def run_detection(
    graph: TransactionGraph,
    config: DetectionConfig | None = None,
    *,
    dataset_id: UUID | None = None,
) -> DetectionRunResult:
    """Convenience entry point for a default sequential detector run."""

    return DetectionOrchestrator().run(graph, config, dataset_id=dataset_id)
