# MuleTrace Detection Engine

## Scope and architecture

The Phase 8 engine is a pure, in-memory layer in `backend/app/detection/`. It
accepts the transaction-preserving `networkx.MultiDiGraph` produced by the
Phase 7 graph builder and returns typed Pydantic findings plus per-detector run
metadata. It does not connect to SQLAlchemy, FastAPI, Redis, or the ground-truth
label table. Dataset ownership and bounded database reads remain the
responsibility of the Phase 7 graph loader before a graph reaches this engine.

`DetectionOrchestrator` executes the enabled detectors sequentially. Each
detector has its own validated configuration, finding limit, and work limit. A
failure is recorded on that detector's execution entry; successful results from
other detectors remain available. Exception messages and transaction details
are not copied into run metadata. The public entry point is:

```python
from app.detection import DetectionConfig, run_detection

result = run_detection(transaction_graph, DetectionConfig())
for finding in result.findings:
    print(finding.detector_name, finding.category, finding.deduplication_key)
```

The default detector order is rapid transfers, fan-in, fan-out, circular
movement, multi-hop movement, unusual account activity, and structuring-like
activity. Every detector is enabled by default. The returned `executions`
collection records `succeeded`, `disabled`, or `failed`, plus scalar statistics.

## Common finding and evidence format

Each `DetectionFinding` contains:

- A stable UUID and SHA-256 deduplication key.
- Detector name/version, category, neutral severity, title, and explanation.
- Dataset, account, and transaction UUID references.
- The inclusive earliest and latest matched event timestamps, normalized to
  UTC.
- Detector-specific evidence and the effective parameters (the `enabled` flag
  is omitted).

Finding identity is derived with UUIDv5 from the dataset, detector/version,
category, ordered account and transaction references, matched time extent, and
detector-specific canonical context. Identical graph inputs and configuration
therefore produce the same identifiers and ordering. Repeated findings with a
matching key are collapsed by the orchestrator. Amounts and per-currency totals
are serialized as decimal strings; transaction UUIDs are retained exactly.

Evidence describes a suspicious pattern or investigative indicator. Severity
(`info`, `low`, `medium`, `high`, `critical`) describes the detector's pattern
signal only. No finding proves fraud, money laundering, intent, or criminal
activity, and this phase does not calculate account risk scores.

## Detectors and defaults

| Detector | Default behavior | Main evidence |
|---|---|---|
| Rapid transfers | At least 3 chronological transactions, no more than 3,600 seconds elapsed, at least 3 distinct accounts, at most 6 transactions in a path. Optional minimum amount is configured by currency. | Continuous account path, ordered transaction references and timestamps, exact amounts, same-currency totals, elapsed time. |
| Fan-in | At least 5 incoming transactions from at least 5 distinct senders in a 86,400-second rolling window. | Center account, unique senders, transaction count, separate currency totals. |
| Fan-out | At least 5 outgoing transactions to at least 5 distinct receivers in a 86,400-second rolling window. | Center account, unique receivers, transaction count, separate currency totals. |
| Circular movement | Directed simple cycles from 3 through 6 accounts with transaction timestamps spanning less than 86,400 seconds. At most 100 cycles are emitted. | Canonical closed account path and one transaction-level edge reference per hop. Parallel transactions can produce distinct cycles. |
| Multi-hop | Paths with 2 to 4 hops in the latest 86,400-second graph window, with at least one intermediary. Optional minimum amount is configured by currency. At most 100 paths are emitted. | Ordered account path and exact transaction, amount, currency, and time references. |
| Unusual activity | Compares the latest 86,400 seconds to up to 14 preceding daily periods. Frequency requires at least 7 periods and 5 historical events by default; an indicator requires at least 3 observed events above mean plus 3 standard deviations. Amounts use per-currency historical median plus 3.5 median absolute deviations, with at least 5 historical events. | Observed and baseline period counts, statistical center/deviation/threshold, currency-specific amount history, and transaction references. |
| Structuring-like activity | Disabled in practice until amount bands are supplied. Configured bands are inclusive, per-currency, and analyzed in 86,400-second windows; at least 3 matching outgoing transactions are required. | Configured band, matching transaction references, exact same-currency total, active UTC days, and inter-transaction intervals. |

All settings are defined and validated in `backend/app/detection/config.py`.
Work controls include detector-specific `max_findings`, `max_windows_examined`,
path/cycle limits, pair limits, and edge-expansion limits. Money thresholds use
`Decimal` and currency-code maps. Different currencies are never added together
or compared against one another.

Structuring bands are deliberately empty by default. Operators must configure
amount bands for their dataset and use case. They are analytical parameters,
not universal legal or reporting thresholds. Overlapping bands for one
currency and floating-point band values are rejected.

## Time-window behavior

Graph timestamps are normalized to UTC. Rolling fan-in, fan-out, and
structuring windows are half-open `[start, start + duration)`: an event exactly
at the end boundary belongs to a later window. Rapid paths require
non-decreasing transaction times and elapsed time strictly below the configured
maximum. Circular movement requires the full cycle's earliest-to-latest event
span to be strictly below its configured window. Multi-hop paths are drawn from
the latest-edge-anchored half-open graph window and must be chronological with
the full path span strictly below the configured maximum. The activity baseline
uses fixed UTC periods immediately before the observation window. A finding's
`time_window` reports the first and last matched event timestamps, not the
entire configured window.

Insufficient activity history is not replaced with a population-wide default.
The unusual-activity detector emits no frequency/amount deviation when the
account lacks the configured minimum baseline and reports insufficient-history
counts in detector metadata.

## Ground truth and persistence boundary

The engine reads only account nodes, transaction edge identifiers, amounts,
currencies, and event timestamps. It does not inspect `ground_truth_labels`,
synthetic generator metadata, or arbitrary account/transaction metadata.
Ground-truth labels remain separate and are suitable only for independent
evaluation code; they are never evidence or an input to detector decisions.

No finding is persisted in Phase 8 and no database migration is required. The
existing `DetectionAlert` row is scoped to one `AnalysisJob` and one
`transaction_id`; a Phase 8 finding can reference multiple transactions and
accounts, so mapping it to one alert row would lose its pattern-level meaning.
`AnalysisJob.result_summary` can hold summary counts but not the complete
finding contract. A later persistence design should preserve the run and
multi-transaction/account evidence explicitly before exposing alert APIs.

## Complexity and current limits

Phase 7 bounds the graph at 100,000 accounts and 500,000 transactions by
default. Phase 8 adds these default limits:

- Rapid transfer enumeration: 50,000 edge expansions, path length 6, and at
  most 100 findings.
- Fan-in/out rolling windows: 100,000 examined windows per detector and at
  most 100 findings.
- Circular movement: 100,000 adjacency/parallel-edge expansions, at most 6
  accounts per cycle, and at most 100 cycles/findings.
- Multi-hop: 10,000 source/target pairs, 1,000 expansions per pair, 100,000
  total expansions, at most 4 hops, and at most 100 paths/findings.
- Unusual activity: bounded baseline horizon of 14 daily periods and at most
  100 findings.
- Structuring: 100,000 rolling windows and at most 100 findings.

The graph is sorted for repeatable traversal. Fan and structuring scans use
sliding windows after sorting. Cycle and path search can still be expensive on
dense graphs; explicit expansion caps stop enumeration and set the detector's
`truncated` statistic. These are synchronous in-memory algorithms. This phase
does not add queues, workers, caching, or incremental graph updates.

## Known limitations

- A graph contains only the records selected by its caller. A filtered or
  partial history can make a real account baseline appear insufficient.
- The unusual-activity baseline compares the latest observation window with
  fixed UTC daily periods. It does not model seasonality or calendar business
  cycles, and zero-MAD baselines can be sensitive to small changes.
- Fan and rapid patterns identify topology/timing, not the economic purpose or
  source of funds.
- Multi-hop detection finds chronological simple paths, but it does not prove
  that each downstream transfer was funded by its preceding transfer.
- Structuring-like detection requires explicitly configured amount bands and
  has no jurisdiction-specific default.
- Detector outputs remain in memory and there are no alert, case, or evaluation
  APIs in this phase.
