"""Learned baselines next to the rule baselines (HANDOFF.md task 4, plus a
linear model), on exactly Stage B's feature vector (FEATURE_COLUMNS) and
decision-point unit, so the only thing that differs from PulseGuard's
Stage B is the learner:

  - isolation_forest: unsupervised. Fit on decision points of benign TRAIN
    users only (it never sees an attack). Score = how anomalous a point is.
  - logistic_regression: supervised linear model on standardised features,
    fit on all TRAIN users -- the "simplest first" model a reviewer expects
    before gradient boosting or a GRU.

Like every other detector here, the alert threshold is chosen on the
validation split's episodes (episode score = max over decision points);
for the Isolation Forest that is the only point at which labels are used.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from services.detection_engine.app.feature_table import to_model_matrix

IFOREST_PARAMS = dict(n_estimators=200, max_samples=256, random_state=0)
LOGREG_PARAMS = dict(max_iter=2000, C=1.0)


class IsolationForestScorer:
    def __init__(self, seed: int):
        self.model = IsolationForest(**{**IFOREST_PARAMS, "random_state": seed})

    def fit(self, view) -> "IsolationForestScorer":
        t = view.table
        benign_train = (t["split"] == "train") & ~t["label_attack"].astype(bool)
        self.model.fit(to_model_matrix(t[benign_train]).to_numpy())
        return self

    def score(self, view) -> np.ndarray:
        # score_samples: higher = more normal. Map so higher = more anomalous.
        return -self.model.score_samples(to_model_matrix(view.table).to_numpy())


class LogisticRegressionScorer:
    def __init__(self, seed: int):
        self.model = make_pipeline(StandardScaler(), LogisticRegression(**LOGREG_PARAMS, random_state=seed))

    def fit(self, view) -> "LogisticRegressionScorer":
        t = view.table
        train = t["split"] == "train"
        self.model.fit(to_model_matrix(t[train]).to_numpy(), t.loc[train, "label_attack"].astype(bool).to_numpy())
        return self

    def score(self, view) -> np.ndarray:
        return self.model.predict_proba(to_model_matrix(view.table).to_numpy())[:, 1]


LEARNED_BASELINES = {
    "isolation_forest": IsolationForestScorer,
    "logistic_regression": LogisticRegressionScorer,
}
