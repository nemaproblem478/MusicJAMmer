"""A three-band equaliser: low shelf, mid peak, high shelf (RBJ "Audio EQ Cookbook" biquads).

Filtering is done a whole block at a time with numpy, exactly: a biquad's
output over a block is its impulse response convolved with the input, plus
what its state carries in from the previous block.
"""

from __future__ import annotations

import math

import numpy as np

LOW_HZ, MID_HZ, HIGH_HZ = 200.0, 1000.0, 4000.0
MID_Q = 0.9
GLIDE_DB_PER_SECOND = 120.0  # how fast a band follows its knob: the full ±12 dB in 0.2 s


def _shelf(freq: float, gain_db: float, sample_rate: int, high: bool) -> tuple[np.ndarray, np.ndarray]:
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * freq / sample_rate
    cos_w0, alpha = math.cos(w0), math.sin(w0) / 2 * math.sqrt(2)  # shelf slope S = 1
    sq = 2 * math.sqrt(a) * alpha
    sign = -1 if high else 1
    b = [
        a * ((a + 1) - sign * (a - 1) * cos_w0 + sq),
        sign * 2 * a * ((a - 1) - sign * (a + 1) * cos_w0),
        a * ((a + 1) - sign * (a - 1) * cos_w0 - sq),
    ]
    den = [
        (a + 1) + sign * (a - 1) * cos_w0 + sq,
        -sign * 2 * ((a - 1) + sign * (a + 1) * cos_w0),
        (a + 1) + sign * (a - 1) * cos_w0 - sq,
    ]
    return np.array(b) / den[0], np.array(den) / den[0]


def _peak(freq: float, gain_db: float, q: float, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * freq / sample_rate
    alpha = math.sin(w0) / (2 * q)
    cos_w0 = math.cos(w0)
    b = [1 + alpha * a, -2 * cos_w0, 1 - alpha * a]
    den = [1 + alpha / a, -2 * cos_w0, 1 - alpha / a]
    return np.array(b) / den[0], np.array(den) / den[0]


def band_filters(low_db: float, mid_db: float, high_db: float, sample_rate: int):
    """The three biquads. A flat band (0 dB) is an exact pass-through."""
    return [
        _shelf(LOW_HZ, low_db, sample_rate, high=False),
        _peak(MID_HZ, mid_db, MID_Q, sample_rate),
        _shelf(HIGH_HZ, high_db, sample_rate, high=True),
    ]


def response_db(low_db: float, mid_db: float, high_db: float, freqs: np.ndarray, sample_rate: int) -> np.ndarray:
    """Gain in dB of the whole EQ at the given frequencies, for drawing its curve."""
    z = np.exp(-2j * np.pi * np.asarray(freqs) / sample_rate)  # z^-1 on the unit circle
    total = np.zeros(len(z))
    for b, a in band_filters(low_db, mid_db, high_db, sample_rate):
        h = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
        total += 20 * np.log10(np.maximum(np.abs(h), 1e-9))
    return total


class _BlockBiquad:
    """One biquad (transposed direct form II) prepared for blocks of n samples.

    State s = (z1, z2). Per sample: y = b0 x + z1, z1' = (b1 - a1 b0) x - a1 z1 + z2,
    z2' = (b2 - a2 b0) x - a2 z1. Over a block that is
        y      = impulse[:n] * x  +  C A^k s       (k = 0..n-1)
        s_next = A^n s  +  sum_k A^(n-1-k) B x[k]
    """

    def __init__(self, b: np.ndarray, a: np.ndarray, n: int) -> None:
        b0, b1, b2 = (float(v) for v in b)
        a1, a2 = float(a[1]), float(a[2])
        bx1, bx2 = b1 - a1 * b0, b2 - a2 * b0  # B
        # Powers of A = [[-a1, 1], [-a2, 0]] applied to B, and C A^k with C = (1, 0).
        impulse = [b0]
        state_rows = []  # C A^k for k = 0..n-1
        drive = []  # A^k B for k = 0..n-1
        r = (1.0, 0.0)  # C A^k
        v = (bx1, bx2)  # A^k B
        for _ in range(n):
            state_rows.append(r)
            drive.append(v)
            impulse.append(v[0])  # h[k+1] = C A^k B
            r = (-a1 * r[0] - a2 * r[1], r[0])
            v = (-a1 * v[0] + v[1], -a2 * v[0])
        self.n = n
        self.impulse = np.array(impulse[:n])
        self.state_rows = np.array(state_rows)  # (n, 2)
        self.drive = np.array(drive[::-1])  # row k is A^(n-1-k) B
        # A^n: its first row is C A^n (where r ended up); its second is e2 A^n = -a2 C A^(n-1).
        last = state_rows[-1]
        self.power = np.array([r, (-a2 * last[0], -a2 * last[1])])

    def process(self, x: np.ndarray, state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        y = np.convolve(x, self.impulse)[: self.n] + self.state_rows @ state
        return y, self.power @ state + self.drive.T @ x


class ChannelEQ:
    """Filters one channel block by block.

    Turning a knob must not click, so the filters keep their state across
    blocks and coefficient changes, and each band glides towards its knob's
    value a little every block instead of jumping there.
    """

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._gains = [0.0, 0.0, 0.0]  # where the bands are now, gliding towards the knobs
        self._states = [np.zeros(2) for _ in range(3)]
        self._biquads: list[_BlockBiquad | None] = [None, None, None]

    def process(self, block: np.ndarray, low_db: float, mid_db: float, high_db: float) -> np.ndarray:
        n = len(block)
        step = GLIDE_DB_PER_SECOND * n / self.sample_rate
        for k, target in enumerate((low_db, mid_db, high_db)):
            if self._gains[k] != target:
                self._gains[k] += min(step, max(-step, target - self._gains[k]))
                self._biquads[k] = None  # only the band being turned is rebuilt
        if all(g == 0 for g in self._gains) and not any(s.any() for s in self._states):
            return block  # flat and at rest: nothing to do
        filters = None
        for k in range(3):
            if self._biquads[k] is None or self._biquads[k].n != n:
                filters = filters or band_filters(*self._gains, self.sample_rate)
                self._biquads[k] = _BlockBiquad(*filters[k], n)
            block, self._states[k] = self._biquads[k].process(block, self._states[k])
        return block
