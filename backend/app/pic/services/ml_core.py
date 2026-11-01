"""Light, dependency-free machine-learning building blocks (Technical Document §13).

Pure Python (no NumPy, scikit-learn or torch) so the Vercel bundle stays small. Everything here is deterministic: the same
data always gives the same model, and every model serialises to plain JSON (``to_dict`` / ``from_dict``) so the model registry
(``ml_registry``) can store it with its metrics.

    LogisticRegression    L2-regularised, standardised features, full-batch gradient descent
    NaiveBayes            multinomial naive Bayes over categorical tokens with Laplace smoothing
    GradientBoostedStumps squared-loss boosting of depth-1 trees (residual correction for the demand forecast)
    holt_forecast         exponential smoothing with trend (price-trend model), parameters chosen by one-step SSE
    hash_vector / cosine  character n-gram hashing embedding (the Siamese-embedding stand-in for duplicate scoring)
    psi / auc / mape      monitoring and evaluation metrics
"""
import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Optional, Sequence


# ---------------------------------------------------------------- metrics
def mape(actual: Sequence[float], forecast: Sequence[float]) -> Optional[float]:
    pairs = [(a, f) for a, f in zip(actual, forecast) if a]
    return sum(abs(f - a) / abs(a) for a, f in pairs) / len(pairs) if pairs else None


def accuracy(truth: Sequence, predicted: Sequence) -> Optional[float]:
    return sum(1 for t, p in zip(truth, predicted) if t == p) / len(truth) if truth else None


def auc(truth: Sequence[int], score: Sequence[float]) -> Optional[float]:
    """Area under the ROC curve (rank statistic, ties count half)."""
    positives = [s for t, s in zip(truth, score) if t]
    negatives = [s for t, s in zip(truth, score) if not t]
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for n in negatives:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(positives) * len(negatives))


def brier(truth: Sequence[int], prob: Sequence[float]) -> Optional[float]:
    return sum((p - t) ** 2 for t, p in zip(truth, prob)) / len(truth) if truth else None


def log_loss(truth: Sequence[int], prob: Sequence[float]) -> Optional[float]:
    if not truth:
        return None
    eps = 1e-9
    return -sum(t * math.log(max(p, eps)) + (1 - t) * math.log(max(1 - p, eps)) for t, p in zip(truth, prob)) / len(truth)


def quantile_edges(values: Sequence[float], bins: int = 10) -> list[float]:
    ordered = sorted(values)
    if not ordered:
        return []
    edges = []
    for i in range(1, bins):
        edges.append(ordered[min(len(ordered) - 1, int(len(ordered) * i / bins))])
    return sorted(set(edges))


def histogram(values: Sequence[float], edges: Sequence[float]) -> list[float]:
    """Share of values per bin delimited by ``edges`` (len(edges)+1 bins)."""
    counts = [0] * (len(edges) + 1)
    for v in values:
        index = 0
        while index < len(edges) and v > edges[index]:
            index += 1
        counts[index] += 1
    total = sum(counts) or 1
    return [c / total for c in counts]


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    """Population stability index between two binned distributions (shares that sum to 1). < 0.1 stable, 0.1-0.25 moderate,
    > 0.25 significant drift."""
    eps = 1e-4
    total = 0.0
    for e, a in zip(expected, actual):
        e, a = max(e, eps), max(a, eps)
        total += (a - e) * math.log(a / e)
    return total


# ---------------------------------------------------------------- logistic regression
def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class LogisticRegression:
    def __init__(self, l2: float = 0.5, epochs: int = 400, lr: float = 0.3):
        self.l2, self.epochs, self.lr = l2, epochs, lr
        self.weights: list[float] = []
        self.bias = 0.0
        self.mean: list[float] = []
        self.scale: list[float] = []

    def _standardise(self, row: Sequence[float]) -> list[float]:
        return [(v - m) / s for v, m, s in zip(row, self.mean, self.scale)]

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int]) -> "LogisticRegression":
        n, d = len(X), len(X[0]) if X else 0
        self.mean = [sum(r[j] for r in X) / n for j in range(d)]
        self.scale = [math.sqrt(sum((r[j] - self.mean[j]) ** 2 for r in X) / n) or 1.0 for j in range(d)]
        Z = [self._standardise(r) for r in X]
        prior = min(max(sum(y) / n, 1e-3), 1 - 1e-3)
        self.weights, self.bias = [0.0] * d, math.log(prior / (1 - prior))
        for _ in range(self.epochs):
            grad_w, grad_b = [0.0] * d, 0.0
            for z, t in zip(Z, y):
                err = _sigmoid(self.bias + sum(w * v for w, v in zip(self.weights, z))) - t
                grad_b += err
                for j in range(d):
                    grad_w[j] += err * z[j]
            self.bias -= self.lr * grad_b / n
            for j in range(d):
                self.weights[j] -= self.lr * (grad_w[j] / n + self.l2 * self.weights[j] / n)
        return self

    def predict_proba(self, row: Sequence[float]) -> float:
        z = self._standardise(row)
        return _sigmoid(self.bias + sum(w * v for w, v in zip(self.weights, z)))

    def to_dict(self) -> dict:
        return {"type": "logistic", "weights": self.weights, "bias": self.bias, "mean": self.mean, "scale": self.scale}

    @classmethod
    def from_dict(cls, data: dict) -> "LogisticRegression":
        model = cls()
        model.weights, model.bias, model.mean, model.scale = data["weights"], data["bias"], data["mean"], data["scale"]
        return model


# ---------------------------------------------------------------- naive Bayes
class NaiveBayes:
    """Multinomial naive Bayes over categorical tokens (``feature=value`` strings) with Laplace smoothing."""

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha
        self.classes: list[str] = []
        self.log_prior: dict[str, float] = {}
        self.counts: dict[str, dict[str, int]] = {}
        self.totals: dict[str, int] = {}
        self.vocab: list[str] = []

    def fit(self, rows: Sequence[Sequence[str]], labels: Sequence[str]) -> "NaiveBayes":
        class_counts = Counter(labels)
        self.classes = sorted(class_counts)
        n = len(labels)
        self.counts = {c: defaultdict(int) for c in self.classes}
        for tokens, label in zip(rows, labels):
            for t in set(tokens):
                self.counts[label][t] += 1
        self.vocab = sorted({t for c in self.counts.values() for t in c})
        self.totals = {c: sum(self.counts[c].values()) for c in self.classes}
        self.log_prior = {c: math.log(class_counts[c] / n) for c in self.classes}
        self.counts = {c: dict(v) for c, v in self.counts.items()}
        return self

    def scores(self, tokens: Sequence[str]) -> dict[str, float]:
        v = len(self.vocab) or 1
        out = {}
        for c in self.classes:
            total = self.totals[c] + self.alpha * v
            out[c] = self.log_prior[c] + sum(math.log((self.counts[c].get(t, 0) + self.alpha) / total) for t in set(tokens))
        return out

    def predict_proba(self, tokens: Sequence[str]) -> dict[str, float]:
        scores = self.scores(tokens)
        top = max(scores.values())
        exp = {c: math.exp(s - top) for c, s in scores.items()}
        z = sum(exp.values())
        return {c: e / z for c, e in exp.items()}

    def predict(self, tokens: Sequence[str]) -> tuple[str, float]:
        proba = self.predict_proba(tokens)
        label = max(sorted(proba), key=lambda c: proba[c])
        return label, proba[label]

    def to_dict(self) -> dict:
        return {"type": "naive_bayes", "alpha": self.alpha, "classes": self.classes, "logPrior": self.log_prior, "counts": self.counts,
                "totals": self.totals, "vocab": self.vocab}

    @classmethod
    def from_dict(cls, data: dict) -> "NaiveBayes":
        model = cls(data["alpha"])
        model.classes, model.log_prior, model.counts = data["classes"], data["logPrior"], data["counts"]
        model.totals, model.vocab = data["totals"], data["vocab"]
        return model


# ---------------------------------------------------------------- gradient-boosted stumps
class GradientBoostedStumps:
    """Squared-loss gradient boosting of depth-1 trees. ``fit`` finds, per round, the (feature, threshold) split that
    minimises the squared error of the residuals and adds ``learning_rate`` times the leaf means."""

    def __init__(self, rounds: int = 40, learning_rate: float = 0.3, min_leaf: int = 2):
        self.rounds, self.learning_rate, self.min_leaf = rounds, learning_rate, min_leaf
        self.base = 0.0
        self.stumps: list[tuple[int, float, float, float]] = []   # feature, threshold, left value, right value

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[float]) -> "GradientBoostedStumps":
        n = len(y)
        self.base = sum(y) / n if n else 0.0
        self.stumps = []
        residual = [t - self.base for t in y]
        d = len(X[0]) if X else 0
        for _ in range(self.rounds):
            best = None
            for j in range(d):
                order = sorted(range(n), key=lambda i: X[i][j])
                total = sum(residual)
                left_sum, left_n = 0.0, 0
                for pos in range(n - 1):
                    i = order[pos]
                    left_sum += residual[i]
                    left_n += 1
                    if X[order[pos + 1]][j] == X[i][j]:
                        continue
                    right_n = n - left_n
                    if left_n < self.min_leaf or right_n < self.min_leaf:
                        continue
                    right_sum = total - left_sum
                    gain = left_sum * left_sum / left_n + right_sum * right_sum / right_n
                    if best is None or gain > best[0] + 1e-12:
                        best = (gain, j, (X[i][j] + X[order[pos + 1]][j]) / 2, left_sum / left_n, right_sum / right_n)
            if best is None:
                break
            _, j, threshold, left_value, right_value = best
            self.stumps.append((j, threshold, left_value * self.learning_rate, right_value * self.learning_rate))
            for i in range(n):
                residual[i] -= self.stumps[-1][2] if X[i][j] <= threshold else self.stumps[-1][3]
        return self

    def predict(self, row: Sequence[float]) -> float:
        return self.base + sum(left if row[j] <= threshold else right for j, threshold, left, right in self.stumps)

    def to_dict(self) -> dict:
        return {"type": "gbstumps", "base": self.base, "stumps": [list(s) for s in self.stumps], "learningRate": self.learning_rate}

    @classmethod
    def from_dict(cls, data: dict) -> "GradientBoostedStumps":
        model = cls(learning_rate=data.get("learningRate", 0.3))
        model.base = data["base"]
        model.stumps = [tuple(s) for s in data["stumps"]]
        return model


# ---------------------------------------------------------------- time series
def exp_smoothing(series: Sequence[float], alpha: float = 0.3) -> float:
    """Level of simple exponential smoothing (the original demand model, α 0.3)."""
    level = series[0]
    for value in series[1:]:
        level = alpha * value + (1 - alpha) * level
    return level


def holt_forecast(series: Sequence[float], horizon: int = 3, alphas=(0.2, 0.4, 0.6, 0.8), betas=(0.05, 0.1, 0.2, 0.3), phi: float = 0.95) -> dict:
    """Exponential smoothing with a damped trend (price-trend model). α and β are the pair with the smallest one-step squared
    error on the series; the forecast adds the damped cumulative trend. Returns the forecast, the fitted parameters, the
    residual standard deviation and an 80 % band."""
    if len(series) < 3:
        value = series[-1] if series else 0.0
        return {"forecast": [value] * horizon, "alpha": None, "beta": None, "trendPerPeriod": 0.0, "sigma": 0.0,
                "low": [value] * horizon, "high": [value] * horizon, "fitted": len(series)}
    best = None
    for alpha in alphas:
        for beta in betas:
            level, trend, sse = series[0], series[1] - series[0], 0.0
            for value in series[1:]:
                predicted = level + phi * trend
                sse += (value - predicted) ** 2
                new_level = alpha * value + (1 - alpha) * predicted
                trend = beta * (new_level - level) + (1 - beta) * phi * trend
                level = new_level
            if best is None or sse < best[0] - 1e-12:
                best = (sse, alpha, beta, level, trend)
    sse, alpha, beta, level, trend = best
    sigma = math.sqrt(sse / max(len(series) - 1, 1))
    forecast, cumulative = [], 0.0
    for h in range(1, horizon + 1):
        cumulative += phi ** h
        forecast.append(level + cumulative * trend)
    z = 1.2816  # 80 % two-sided
    return {"forecast": forecast, "alpha": alpha, "beta": beta, "trendPerPeriod": trend, "sigma": sigma,
            "low": [f - z * sigma * math.sqrt(h + 1) for h, f in enumerate(forecast)],
            "high": [f + z * sigma * math.sqrt(h + 1) for h, f in enumerate(forecast)], "fitted": len(series)}


# ---------------------------------------------------------------- hashing n-gram embedding
_WORD = re.compile(r"[^a-z0-9]+")
_LEGAL = re.compile(r"\b(?:the|messrs|pvt|private|ltd|limited|llp|inc|llc|plc|co|company|corp|corporation)\b")


def normalise_text(text: str) -> str:
    value = (text or "").lower().replace("&", " and ")
    value = re.sub(r"^\s*m\s*/\s*s\b\.?", " ", value).replace(".", "")
    value = _LEGAL.sub(" ", _WORD.sub(" ", value))
    return re.sub(r"\s+", " ", value).strip()


def hash_vector(text: str, dim: int = 512, ngrams: tuple = (2, 3, 4), words: bool = True) -> dict[int, float]:
    """Sparse, L2-normalised embedding of a text: character n-grams (with word boundaries) hashed into ``dim`` buckets with a
    sign hash (the hashing trick), plus whole words. Similar spellings share most n-grams, so cosine similarity is high."""
    base = normalise_text(text)
    padded = f" {base} "
    vec: dict[int, float] = defaultdict(float)

    def add(token: str, weight: float) -> None:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[index] += sign * weight

    for n in ngrams:
        for i in range(len(padded) - n + 1):
            add(f"c{n}:{padded[i:i + n]}", 1.0)
    if words:
        for w in base.split():
            add(f"w:{w}", 2.0)
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def ridge_fit(X: Sequence[Sequence[float]], y: Sequence[float], l2: float = 1e-6) -> list[float]:
    """Ordinary least squares with a tiny ridge term via the normal equations (Gauss-Jordan); the first coefficient is the
    intercept. Used by the parametric should-cost calibration."""
    n, d = len(X), (len(X[0]) if X else 0) + 1
    A = [[0.0] * d for _ in range(d)]
    b = [0.0] * d
    for row, t in zip(X, y):
        r = [1.0, *row]
        for i in range(d):
            b[i] += r[i] * t
            for j in range(d):
                A[i][j] += r[i] * r[j]
    for i in range(1, d):
        A[i][i] += l2 * n
    for col in range(d):
        pivot = max(range(col, d), key=lambda r_: abs(A[r_][col]))
        if abs(A[pivot][col]) < 1e-12:
            continue
        A[col], A[pivot] = A[pivot], A[col]
        b[col], b[pivot] = b[pivot], b[col]
        div = A[col][col]
        A[col] = [v / div for v in A[col]]
        b[col] /= div
        for r_ in range(d):
            if r_ != col and A[r_][col]:
                factor = A[r_][col]
                A[r_] = [v - factor * c for v, c in zip(A[r_], A[col])]
                b[r_] -= factor * b[col]
    return b
