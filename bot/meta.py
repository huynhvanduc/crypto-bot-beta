import warnings

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES

warnings.filterwarnings("ignore", message="X does not have valid feature names")

MODELS = ("logreg", "lgbm")


def make_model(kind: str = "logreg"):
    if kind == "logreg":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=2000))
    if kind == "lgbm":
        return LGBMClassifier(
            n_estimators=200, learning_rate=0.03, num_leaves=8, max_depth=3,
            min_child_samples=50, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
            reg_lambda=1.0, random_state=0, verbose=-1,
        )
    raise ValueError(kind)


def walk_forward_proba(
    cands: pd.DataFrame,
    first_test: pd.Timestamp,
    kind: str = "logreg",
    train_months: int | None = None,
    step: str = "3MS",
    min_train: int = 200,
) -> pd.Series:
    data = cands.dropna(subset=FEATURES)
    proba = pd.Series(np.nan, index=cands.index)
    end = cands["signal_time"].max() + pd.Timedelta(days=1)
    edges = list(pd.date_range(first_test, end, freq=step, tz=first_test.tz))
    if not edges or edges[0] != first_test:
        edges.insert(0, first_test)
    edges.append(end)

    for t0, t1 in zip(edges[:-1], edges[1:]):
        train = recent_window(data[data["exit_time"] < t0], t0, train_months)
        test = data[(data["signal_time"] >= t0) & (data["signal_time"] < t1)]
        if len(train) < min_train or test.empty or train["win"].nunique() < 2:
            continue
        model = make_model(kind).fit(train[FEATURES], train["win"])
        proba.loc[test.index] = model.predict_proba(test[FEATURES])[:, 1]
    return proba


def recent_window(data: pd.DataFrame, until: pd.Timestamp, months: int | None) -> pd.DataFrame:
    if months is None:
        return data
    return data[data["signal_time"] >= until - pd.DateOffset(months=months)]


def fit_final(cands: pd.DataFrame, kind: str = "logreg"):
    data = cands.dropna(subset=FEATURES)
    return make_model(kind).fit(data[FEATURES], data["win"])


def importance(model, kind: str) -> pd.Series:
    if kind == "logreg":
        vals = model[-1].coef_[0]
    else:
        vals = model.booster_.feature_importance("gain")
        vals = vals / vals.sum()
    return pd.Series(vals, index=FEATURES).sort_values(key=abs, ascending=False)
