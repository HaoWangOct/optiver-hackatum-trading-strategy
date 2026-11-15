"""Bounded rolling Fourier forecasts. No exchange calls happen in this worker."""
import cmath
import math
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Prediction:
    price: float
    volume: float
    error: float
    created: float
    observed: float = 0.0


def extrapolate(values, harmonics=4):
    """Detrend, retain strongest positive frequencies, extrapolate one sample."""
    n = len(values)
    if n < 8:
        return float(values[-1])
    mean = sum(values) / n
    center = (n - 1) / 2
    slope = sum((i - center) * (v - mean) for i, v in enumerate(values))
    slope /= sum((i - center) ** 2 for i in range(n))
    residual = [v - mean - slope * (i - center) for i, v in enumerate(values)]
    # Fixed upper bound on frequencies and samples keeps runtime bounded.
    spectrum = []
    for k in range(1, min(n // 2, 24)):
        coefficient = sum(v * cmath.exp(-2j * math.pi * k * i / n)
                          for i, v in enumerate(residual)) / n
        spectrum.append((abs(coefficient), coefficient, k))
    wave = sum(2 * (c * cmath.exp(2j * math.pi * k)).real
               for _, c, k in sorted(spectrum, reverse=True)[:harmonics])
    return mean + slope * (n - center) + wave


class HistoryManager:
    def __init__(self, window=128, interval=1.0, min_samples=32):
        self.window, self.interval, self.min_samples = window, interval, min_samples
        self.history = {}
        self.predictions = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="fourier", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def add(self, instrument, aggressor_side, price, volume, timestamp):
        if aggressor_side not in ("bid", "ask") or not all(
                math.isfinite(x) for x in (price, volume, timestamp)):
            return
        if price <= 0 or volume <= 0:
            return
        key = (instrument, aggressor_side)
        with self.lock:
            series = self.history.setdefault(key, deque(maxlen=self.window))
            if series and timestamp < series[-1][0]:
                return
            series.append((timestamp, price, volume))

    def get(self, instrument, max_age=3.0):
        with self.lock:
            return {side: p for (iid, side), p in self.predictions.items()
                    if iid == instrument and time.monotonic() - p.created < max_age
                    and time.time() - p.observed < max_age}

    def calculate(self):
        with self.lock:
            snapshots = {k: list(v) for k, v in self.history.items()}
        result = {}
        for key, ticks in snapshots.items():
            # Trade arrivals are irregular: put them on a uniform time grid.
            if len(ticks) < self.min_samples or ticks[-1][0] <= ticks[0][0]:
                continue
            step = (ticks[-1][0] - ticks[0][0]) / (len(ticks) - 1)
            grid, j = [], 0
            for i in range(len(ticks)):
                t = ticks[0][0] + i * step
                while j + 1 < len(ticks) and ticks[j + 1][0] <= t:
                    j += 1
                grid.append(ticks[j])
            prices, volumes = [v[1] for v in grid], [v[2] for v in grid]
            # Forward validation: each prediction only uses preceding samples.
            errors = [abs(extrapolate(prices[:i]) - prices[i])
                      for i in range(len(prices) - 8, len(prices))]
            result[key] = Prediction(extrapolate(prices), max(1, extrapolate(volumes)),
                                     sum(errors) / len(errors), time.monotonic(), ticks[-1][0])
        with self.lock:
            self.predictions = result

    def _run(self):
        while not self.stop_event.wait(self.interval):
            self.calculate()
