"""Dependency-free rolling Fourier extrapolation for short windows.

The naive DFT is intentionally O(n^2). Use bounded window sizes; it is not
designed for latency-critical live execution.
"""
import cmath
import math
from collections.abc import Sequence


def fourier_extrapolate(prices: Sequence[float], horizon: int = 1,
                        max_window: int = 64, keep_frequencies: int = 3) -> float:
    """Predict one future level using dominant nonzero DFT components.

    Returns a research baseline, *not* a validated alpha forecast.
    """
    if horizon < 1 or max_window < 4 or keep_frequencies < 0:
        raise ValueError("Invalid forecasting parameters")
    samples = [float(x) for x in prices[-max_window:]]
    n = len(samples)
    if n < 4 or any(not math.isfinite(x) for x in samples):
        raise ValueError("At least 4 finite prices are required")
    mean = sum(samples) / n
    demeaned = [x - mean for x in samples]
    coeffs = [
        sum(x * cmath.exp(-2j * math.pi * k * t / n)
            for t, x in enumerate(demeaned)) / n
        for k in range(n)
    ]
    # Pair conjugate frequencies to reconstruct a real-valued signal.
    candidates = list(range(1, (n - 1) // 2 + 1))
    chosen = sorted(candidates, key=lambda k: abs(coeffs[k]), reverse=True)[:keep_frequencies]
    prediction = mean
    future_t = n - 1 + horizon
    for k in chosen:
        prediction += 2 * (coeffs[k] * cmath.exp(2j * math.pi * k * future_t / n)).real
    if n % 2 == 0 and keep_frequencies and len(chosen) < keep_frequencies:
        k = n // 2
        prediction += (coeffs[k] * cmath.exp(2j * math.pi * k * future_t / n)).real
    return prediction
