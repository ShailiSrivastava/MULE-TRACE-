# MuleTrace Machine Learning and Anomaly Detection

Phase 10 adds a backend-only, unsupervised anomaly analysis package in
`backend/app/ml/`. It complements the deterministic Phase 8 detectors. Anomaly
scores are prioritization indicators, not probabilities and not findings of
fraud or criminal conduct. No public ML API, worker, graph endpoint, or
production model server is included.

## Data flow and separation

The supported workflow is:

1. Load a bounded, owner-scoped Phase 7 graph through
   `extract_owned_dataset_features` in `app/services/ml_features.py`.
2. Choose either the account or transaction feature batch and split it using
   `grouped_holdout_split` before fitting any preprocessing or estimator.
3. Call `fit_model` with training vectors only. Preprocessing statistics and
   the feature explanation baseline are derived only from those vectors.
4. Call `predict` on new or held-out vectors. Prediction does not fit or alter
   preprocessing state and does not receive labels.
5. For evaluation only, load explicitly configured labels using
   `load_binary_ground_truth`, then pass held-out predictions and that mapping
   to `evaluate_predictions`.
6. Optionally convert anomaly predictions to Phase 9 findings with
   `predictions_to_detection_run` and pass the result through the existing
   finding persistence service.

Feature extraction, preprocessing, model fitting, inference, and registry
metadata code do not import or query `GroundTruthLabel`. The isolated
evaluation service maps only configured positive and negative label codes.
Other labels remain unknown, and unlabeled records are never assumed normal.
The current database label model labels transactions; account-level evaluation
requires an explicit account label mapping from a separate trusted source.

## Feature schema 1.0

All transaction reads are bounded by the analysis cutoff. Transactions after
the cutoff are excluded. A transaction's historical features use events with
strictly earlier timestamps; transactions sharing a timestamp are all scored
against the state before that timestamp group is applied. This avoids ordering
leakage between simultaneous records. Timestamps are normalized to UTC.

Account features include:

- Incoming, outgoing, and total transaction counts.
- Incoming and outgoing amount totals, averages, and population variances for
  each currency observed in the bounded graph. Currencies remain separate;
  there is no cross-currency sum.
- Unique incoming, outgoing, and total counterparties.
- Transaction frequency per day over the observed period, with a one-day
  minimum denominator; average seconds between individual transactions,
  including zero-second gaps for simultaneous transactions.
- Counts in trailing 1-hour, 24-hour, 7-day, and 30-day windows.
- Smoothed incoming/outgoing count ratio, graph in/out degree, and normalized
  in/out degree centrality computed on the cutoff-filtered graph.

Transaction features include currency-specific amount columns, sender and
receiver historical activity counts, trailing 30-day activity, directional
counterparty counts, seconds since each account's prior transaction, and
same-currency ratios and z-scores against prior outgoing/incoming amounts.
Missing historical comparisons are `None` and handled by the fitted
preprocessor. Calendar hour and weekday are encoded with sine/cosine features.

Financial sums, means, variances, ratios, and historical amount statistics use
`Decimal`. Only the preprocessing boundary converts values to finite float64
model inputs. Ground-truth labels, dataset names, account external identifiers,
and raw transaction metadata are not feature inputs. The graph loader uses the
existing bounded graph limits; accounts without transactions at the cutoff do
not form model samples.

## Preprocessing

`FeaturePreprocessor` fixes a sorted feature-name schema and entity type during
training. It applies median imputation, an explicit missingness indicator for
every feature, and `StandardScaler` by default. Constant columns remain in the
schema and scale to finite zeros. Entirely missing training columns are kept
and imputed by the configured scikit-learn behavior. Inference rejects a
different entity type, feature schema version, or unexpected feature name; a
missing known field is represented as missing and uses training-only
statistics. NaN, infinity, booleans, and nonnumeric input are rejected before
model fitting.

## Models and score interpretation

All estimators implement the common `AnomalyModel` interface and record the
configured model name and version.

| Model | Default configuration | Anomaly indicator |
|---|---|---|
| Isolation Forest | 100 estimators, contamination 0.1, automatic max samples, seed 42 | Negated `score_samples`; the estimator's configured decision threshold labels anomalies |
| Local Outlier Factor | 20 neighbors, contamination 0.1, novelty mode enabled | Negated novelty `score_samples`; training requires more samples than neighbors |
| K-Means | 3 clusters, 10 initializations, 95th-percentile distance threshold, seed 42 | Euclidean distance to assigned centroid; output also includes cluster ID |

Each prediction records the raw score and a 0–1 normalized anomaly score based
on the training score range, as well as an `ANOMALY` or `NORMAL` label. The
normalized value is not a probability. Degenerate scores normalize to zero.
LOF and K-Means fail with explicit minimum-sample errors; they do not silently
substitute another estimator. K-Means also rejects data with fewer distinct
vectors than configured clusters.

## Explanations

Explanations deterministically compare actual input feature values with robust
training medians and median-absolute-deviation scales (with a variance-based
fallback). The output names unusually high or low features and shows the
observed value and baseline. These descriptions explain feature deviations;
they are not causal attribution and do not claim to reproduce an estimator's
internal decision process. A high score must not be interpreted as proof of
suspicious activity.

## Training and evaluation methodology

`grouped_holdout_split` uses `FeatureVector.group_id` and a configured random
seed. Account-level samples are grouped by account; transaction samples are
grouped by their connected account component so linked entities do not cross
the train/evaluation boundary. The training partition is passed to `fit_model`;
only predictions for the held-out partition are evaluated. Groups must be
disjoint and at least two independent groups must exist. Group-based holdout
is the implemented method; a chronological/time holdout is not currently
implemented.

Evaluation reports precision, recall, F1, confusion matrix, false-positive
rate, average precision, and precision-recall points only when enough explicit
held-out labels include both classes. Otherwise, status is
`INSUFFICIENT_LABELS`, metric fields remain empty, and the result says that
predictive accuracy cannot be established. The service does not manufacture
labels, infer that unlabelled data is negative, or claim unmeasured model
performance.

## Registry and persistence

`ModelRegistry` holds fitted estimator instances, fitted preprocessors, and
aggregate explanation baselines in process memory, keyed by immutable model
name/version. Re-registering a version fails. No pickle or joblib artifact is
written or loaded, and no raw training vectors are retained in the registry.

The additive Alembic revision `b18f3a9d2c74` creates `ml_model_registry` for
durable reproducibility metadata: model/version, feature schema, entity type,
training dataset reference/time/sample count, feature names, parameters,
preprocessing configuration, evaluation metrics, seed, status, and creator.
Model metadata is owner-scoped and audited. Unique model name/version pairs
cannot be overwritten. Fitted estimators are process-local and are lost at
restart; durable metadata alone is not a deployable model artifact, so a model
must be retrained before inference after restart.

## Phase 9 adapter

`predictions_to_detection_run` converts only `ANOMALY` predictions to findings
in category `ml_anomaly`. Evidence contains model name/version, feature schema,
scores, feature values, timestamps, parameters, and deterministic explanations.
Finding identity is stable for dataset, model/version, schema, and entity, so
repeated output does not create duplicate canonical findings. Callers can
combine these findings with separate rule output and persist the combined run
through the existing Phase 9 service. Model classes do not call risk scoring, mutate risk assessments, or
rewrite rule detector output; Phase 9 scoring remains an independent step.

## Performance and known limitations

Feature extraction is linear in the bounded graph's vertices and transactions,
plus per-account currency aggregation and graph metric work. Preprocessing is
linear in sample count times feature count. Estimator costs depend on their
scikit-learn implementations and configured sample/cluster sizes. Processing
is local and synchronous; distributed jobs and persistent model artifacts are
outside this phase.

Feature schema 1.0 is dataset-currency-dependent: a new observed currency can
add columns and therefore requires a new compatible training schema. Degree
centrality is a selected topology measure, not a full graph embedding.
Thresholds and model scores are dataset- and preprocessing-dependent. The
unsupervised estimators do not provide calibrated risk probabilities, and
group holdout may not measure future-time generalization. Explanations are
descriptive rather than causal. The service has no public API or model-serving
endpoint in Phase 10.
