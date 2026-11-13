"""Hourly availability: how a day's chance spreads across its hours (factors at the hour scale).

Data: for each UTC hour, ``k`` records of the taxon and ``n`` records of its group (iNaturalist
hourly counts; the group stands in for when people are out looking). Model, one row per hour
with ``n > 0``::

    logit P(a group record in hour h is the taxon) = b0 + Σ_f f(factor_f(h))

fitted as an aggregated binomial (``y = k/n``, weight ``n``) with the same penalized logistic
model as Level 1 (conditions/model.py), so terms are categorical levels (diel phase, tide stage,
moonlight, hours after sunset) or smooth numbers (tide height).

**Gate.** Trained on hours before ``split``, tested on hours after it: the model must beat
"the taxon's share of its group is the same at every hour" (intercept only) on held-out
binomial log loss, with the lower end of a 90% day-block bootstrap interval above zero and a
practical gain of at least 0.5%. Each factor is also dropped in turn (scorecard).

**Serving.** For an outing in hour h the daily odds are multiplied by
``exp(η(h) − log m̄)``, where ``η`` is the factor part and ``m̄`` its effort-weighted mean
``exp(η)`` over all hours, so averaging over a typical day's effort leaves the daily forecast
unchanged: the hourly model only redistributes it.

Caveat: records reflect activity, detectability and observer habits together. The output is
when the species is *recorded* relatively more often, an availability prior, not behavior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from wildlife_radar.conditions.model import OffsetLogit, TermSpec, block_bootstrap, log_loss

MIN_TRAIN_RECORDS = 50
MIN_TEST_RECORDS = 20
PRACTICAL_GAIN = 0.005
"""Relative reduction of held-out log loss a model must reach to be used."""

HOURLY_SCHEMA = """
CREATE TABLE IF NOT EXISTS hourly_models (
    region_id VARCHAR, taxon_id VARCHAR, model JSON, log_norm DOUBLE,
    n_train BIGINT, n_test BIGINT, k_train BIGINT, k_test BIGINT,
    loss_base DOUBLE, loss_model DOUBLE, gain DOUBLE, ci_lo DOUBLE, ci_hi DOUBLE,
    passes BOOLEAN, split DATE, evaluated_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS hourly_scorecard (
    region_id VARCHAR, taxon_id VARCHAR, term VARCHAR, signal VARCHAR, hypothesis BOOLEAN,
    delta DOUBLE, ci_lo DOUBLE, ci_hi DOUBLE, verdict VARCHAR, effects JSON, peak VARCHAR,
    expected VARCHAR, review VARCHAR, evaluated_at TIMESTAMP
);
"""


@dataclass
class HourlyTerm:
    term: str
    signal: str
    hypothesis: bool
    delta: float
    ci: tuple[float, float]
    verdict: str
    effects: dict[str, float] = field(default_factory=dict)
    """Log-odds of each level relative to the reference (categorical terms)."""
    peak: str | None = None
    expected: str | None = None
    review: str | None = None


@dataclass
class HourlyFit:
    terms: list[TermSpec]
    model: OffsetLogit | None
    log_norm: float = 0.0
    n_train: int = 0
    n_test: int = 0
    k_train: int = 0
    k_test: int = 0
    loss_base: float = math.nan
    loss_model: float = math.nan
    gain: float = math.nan
    ci: tuple[float, float] = (math.nan, math.nan)
    passes: bool = False
    scorecard: list[HourlyTerm] = field(default_factory=list)
    note: str | None = None


def design(
    hours: list[datetime], terms: list[TermSpec], value
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Factor values per hour (``value(signal, hour)``) and a mask of hours where all are known."""
    signals = {t.signal: np.array([value(t.signal, h) for h in hours], dtype=object) for t in terms}
    ok = np.ones(len(hours), dtype=bool)
    for arr in signals.values():
        ok &= np.array([v is not None for v in arr])
    return {s: np.where(ok, arr, 0).astype(float) for s, arr in signals.items()}, ok


def _sub(signals: dict[str, np.ndarray], idx) -> dict[str, np.ndarray]:
    return {s: a[idx] for s, a in signals.items()}


def fit_hourly(
    taxon: dict[datetime, int],
    effort: dict[datetime, int],
    terms: list[TermSpec],
    value,
    split: date,
    *,
    offset_hours: int = 0,
    expectations: dict[str, tuple[str, ...]] | None = None,
    reps: int = 200,
    seed: int = 7,
) -> HourlyFit:
    """Fit, gate and score the hourly terms for one taxon (see the module docstring)."""
    out = HourlyFit(terms=terms, model=None)
    hours = sorted(h for h, n in effort.items() if n > 0)
    if not hours or not terms:
        out.note = "no hours or no candidate terms"
        return out
    signals, ok = design(hours, terms, value)
    hours = [h for h, keep in zip(hours, ok, strict=True) if keep]
    signals = _sub(signals, ok)
    n = np.array([effort[h] for h in hours], dtype=float)
    k = np.minimum(np.array([taxon.get(h, 0) for h in hours], dtype=float), n)
    y = k / n
    days = np.array([(h + timedelta(hours=offset_hours)).date().toordinal() for h in hours])
    test = days >= split.toordinal()
    train = ~test
    out.n_train, out.n_test = int(n[train].sum()), int(n[test].sum())
    out.k_train, out.k_test = int(k[train].sum()), int(k[test].sum())
    if out.k_train < MIN_TRAIN_RECORDS or out.k_test < MIN_TEST_RECORDS:
        out.note = f"too few records ({out.k_train} train, {out.k_test} test)"
        return out
    zero = np.zeros(len(hours))

    def fit(ts: list[TermSpec], idx) -> OffsetLogit:
        return OffsetLogit(ts).fit(_sub(signals, idx), y[idx], zero[idx], n[idx])

    base = fit([], train)
    full = fit(terms, train)
    held = _sub(signals, test)
    p_base = base.predict(held, zero[test])
    p_full = full.predict(held, zero[test])
    yt, nt, bt = y[test], n[test], days[test]
    out.loss_base = log_loss(yt, p_base, nt)
    out.loss_model = log_loss(yt, p_full, nt)
    out.gain = out.loss_base - out.loss_model

    def gain(idx, pa=p_base, pb=p_full) -> float:
        return log_loss(yt[idx], pa[idx], nt[idx]) - log_loss(yt[idx], pb[idx], nt[idx])

    out.ci = block_bootstrap(bt, gain, reps=reps, seed=seed)
    out.passes = bool(
        out.ci[0] > 0 and out.loss_base > 0 and out.gain / out.loss_base >= PRACTICAL_GAIN
    )
    # Scorecard: drop each term in turn (held-out gain of keeping it).
    expectations = expectations or {}
    for t in terms:
        others = [u for u in terms if u.name != t.name]
        p_wo = fit(others, train).predict(held, zero[test])

        def term_gain(idx, pa=p_wo, pb=p_full) -> float:
            return log_loss(yt[idx], pa[idx], nt[idx]) - log_loss(yt[idx], pb[idx], nt[idx])

        ci = block_bootstrap(bt, term_gain, reps=reps, seed=seed)
        delta = log_loss(yt, p_wo, nt) - out.loss_model
        verdict = "supported" if ci[0] > 0 else "contradicted" if ci[1] < 0 else "inconclusive"
        effects = full.category_effects(t.name) if t.shape == "categorical" else {}
        peak = max(effects, key=effects.get) if effects else None
        expected = expectations.get(t.signal)
        review = None
        if verdict == "contradicted":
            review = "the term makes held-out predictions worse"
        elif verdict == "supported" and expected and peak not in expected:
            review = f"recorded most at {peak}, not {'/'.join(expected)} as the profile states"
        out.scorecard.append(
            HourlyTerm(
                term=t.name,
                signal=t.signal,
                hypothesis=t.hypothesis,
                delta=delta,
                ci=ci,
                verdict=verdict,
                effects={c: round(v, 4) for c, v in effects.items()},
                peak=peak,
                expected="/".join(expected) if expected else None,
                review=review,
            )
        )
    if out.passes:
        # Serve a model fitted on all hours, normalized over all hours' effort.
        everything = np.ones(len(hours), dtype=bool)
        model = fit(terms, everything)
        eta = np.log(model.predict(signals, zero) / (1 - model.predict(signals, zero)))
        eta -= model.intercept
        out.log_norm = float(np.log(np.sum(n * np.exp(eta)) / np.sum(n)))
        out.model = model
    return out


def multiplier(model: OffsetLogit, log_norm: float, signals: dict[str, np.ndarray]) -> np.ndarray:
    """Odds multipliers for hours with these factor values (1 = a typical hour)."""
    p = model.predict(signals, np.zeros(len(next(iter(signals.values())))))
    eta = np.log(p / (1 - p)) - model.intercept
    return np.exp(eta - log_norm)


def persist(conn, region_id: str, taxon_id: str, fit: HourlyFit, split: date, now) -> None:
    import json

    conn.execute(HOURLY_SCHEMA)
    for table in ("hourly_models", "hourly_scorecard"):
        conn.execute(
            f"DELETE FROM {table} WHERE region_id = ? AND taxon_id = ?", [region_id, taxon_id]
        )
    now_n = now.replace(tzinfo=None)

    def num(x: float) -> float | None:
        return None if x is None or math.isnan(x) else float(x)

    conn.execute(
        "INSERT INTO hourly_models VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            region_id,
            taxon_id,
            json.dumps(fit.model.to_dict()) if fit.model else None,
            fit.log_norm,
            fit.n_train,
            fit.n_test,
            fit.k_train,
            fit.k_test,
            num(fit.loss_base),
            num(fit.loss_model),
            num(fit.gain),
            num(fit.ci[0]),
            num(fit.ci[1]),
            fit.passes,
            split,
            now_n,
        ],
    )
    for t in fit.scorecard:
        conn.execute(
            "INSERT INTO hourly_scorecard VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                region_id,
                taxon_id,
                t.term,
                t.signal,
                t.hypothesis,
                num(t.delta),
                num(t.ci[0]),
                num(t.ci[1]),
                t.verdict,
                json.dumps(t.effects),
                t.peak,
                t.expected,
                t.review,
                now_n,
            ],
        )
