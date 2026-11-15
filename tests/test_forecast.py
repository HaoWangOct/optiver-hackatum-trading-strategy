import unittest
import math
from src.forecast import fourier_extrapolate


class FourierTests(unittest.TestCase):
    def test_constant_series(self):
        self.assertAlmostEqual(fourier_extrapolate([42] * 16), 42.0, places=6)

    def test_periodic_signal(self):
        signal = [100 + 2 * math.cos(2 * math.pi * k / 8) for k in range(32)]
        forecast = fourier_extrapolate(signal, horizon=1, max_window=32)
        self.assertAlmostEqual(forecast, 102, places=5)

    def test_too_short(self):
        with self.assertRaises(ValueError):
            fourier_extrapolate([1, 2, 3])

    def test_nonfinite(self):
        with self.assertRaises(ValueError):
            fourier_extrapolate([1, 2, 3, float("nan")])


if __name__ == "__main__":
    unittest.main()
