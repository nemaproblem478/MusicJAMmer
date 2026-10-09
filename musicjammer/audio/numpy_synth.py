"""A small polyphonic synth: one oscillator and an ADSR envelope per voice,
then a three-band EQ and a mix level per channel.

Events from the game thread go through a queue and are applied at the start of
each audio block, so the audio callback never waits on the game loop.
"""

from __future__ import annotations

import math
import queue

import numpy as np

from .engine import NoteEngine, Param
from .eq import ChannelEQ

WAVEFORMS = ("sine", "triangle", "saw", "square")

_ATTACK, _DECAY, _SUSTAIN, _RELEASE = range(4)
_E5 = math.exp(-5.0)
_VOICE_LEVEL = 0.3
_GAIN_GLIDE = 0.15  # seconds for a channel's mix level to go from 0 to 1


def midi_to_freq(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12)


def _poly_blep(t: np.ndarray, dt: float) -> np.ndarray:
    """Band-limiting correction around the discontinuity of a saw/square wave."""
    y = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt
    y[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt
    y[m] = x * x + x + x + 1.0
    return y


def _exp_segment(start: float, end: float, t0: int, count: int, length: int) -> np.ndarray:
    """Exponential-looking curve from start to end over `length` samples that lands exactly on end."""
    x = np.arange(t0 + 1, t0 + count + 1) / length
    shape = (np.exp(-5.0 * x) - _E5) / (1.0 - _E5)
    return end + (start - end) * shape


class _Voice:
    __slots__ = ("channel", "note", "amp", "freq", "phase", "stage", "t", "level", "start_level", "done")

    def __init__(self, channel: int, note: int, velocity: int) -> None:
        self.channel = channel
        self.note = note
        self.amp = velocity / 127.0
        self.freq = midi_to_freq(note)
        self.phase = 0.0
        self.stage = _ATTACK
        self.t = 0
        self.level = 0.0
        self.start_level = 0.0
        self.done = False

    @property
    def released(self) -> bool:
        return self.stage == _RELEASE

    def release(self) -> None:
        if not self.released:
            self.stage = _RELEASE
            self.t = 0
            self.start_level = self.level

    def envelope(self, n: int, p: dict, sr: int) -> np.ndarray:
        out = np.zeros(n)
        i = 0
        while i < n and not self.done:
            if self.stage == _SUSTAIN:
                out[i:] = self.level = p["sustain"]
                break
            seconds = {_ATTACK: p["attack"], _DECAY: p["decay"], _RELEASE: p["release"]}[self.stage]
            length = max(1, int(seconds * sr))
            if self.t >= length:  # stage finished (or its length was just shortened)
                self._next_stage(p)
                continue
            k = min(n - i, length - self.t)
            if self.stage == _ATTACK:
                x = np.arange(self.t + 1, self.t + k + 1) / length
                seg = self.start_level + (1.0 - self.start_level) * x
            elif self.stage == _DECAY:
                seg = _exp_segment(1.0, p["sustain"], self.t, k, length)
            else:
                seg = _exp_segment(self.start_level, 0.0, self.t, k, length)
            out[i : i + k] = seg
            self.level = seg[-1]
            self.t += k
            i += k
        return out

    def _next_stage(self, p: dict) -> None:
        self.t = 0
        if self.stage == _ATTACK:
            self.stage, self.level = _DECAY, 1.0
        elif self.stage == _DECAY:
            self.stage, self.level = _SUSTAIN, p["sustain"]
        else:
            self.done, self.level = True, 0.0

    def oscillator(self, n: int, waveform: str, sr: int) -> np.ndarray:
        dt = self.freq / sr
        t = (self.phase + dt * np.arange(n)) % 1.0
        self.phase = (self.phase + dt * n) % 1.0
        if waveform == "sine":
            return np.sin(2.0 * np.pi * t)
        if waveform == "triangle":
            return 1.0 - 4.0 * np.abs(t - 0.5)
        if waveform == "saw":
            return 2.0 * t - 1.0 - _poly_blep(t, dt)
        square = np.where(t < 0.5, 1.0, -1.0)
        return square + _poly_blep(t, dt) - _poly_blep((t + 0.5) % 1.0, dt)


class NumpySynth(NoteEngine):
    def __init__(self, sample_rate: int = 44100, block_size: int = 256, max_voices: int = 32) -> None:
        super().__init__()
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.max_voices = max_voices
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._voices: list[_Voice] = []
        self._gain = 1.0
        self._channel_gain_now = [1.0] * self.NUM_CHANNELS
        self._eqs = [ChannelEQ(sample_rate) for _ in range(self.NUM_CHANNELS)]
        self._stream = None

    @classmethod
    def params(cls) -> list[Param]:
        return [
            Param("waveform", "Wave", "triangle", choices=WAVEFORMS, group="wave"),
            Param("attack", "Attack", 0.01, 0.001, 2.0, "s", log=True, group="envelope"),
            Param("decay", "Decay", 0.3, 0.005, 3.0, "s", log=True, group="envelope"),
            Param("sustain", "Sustain", 0.7, 0.0, 1.0, group="envelope"),
            Param("release", "Release", 0.4, 0.005, 4.0, "s", log=True, group="envelope"),
            Param("eq_low", "Low", 0.0, -12.0, 12.0, "dB", group="eq"),
            Param("eq_mid", "Mid", 0.0, -12.0, 12.0, "dB", group="eq"),
            Param("eq_high", "High", 0.0, -12.0, 12.0, "dB", group="eq"),
            Param("volume", "Volume", 0.8, 0.0, 1.0, group="eq"),
        ]

    # --- events (called from the game thread) ---

    def note_on(self, channel: int, note: int, velocity: int = 100) -> None:
        self._events.put(("on", channel, note, velocity))

    def note_off(self, channel: int, note: int) -> None:
        self._events.put(("off", channel, note))

    def all_notes_off(self, channel: int) -> None:
        self._events.put(("all_off", channel))

    @property
    def active_voices(self) -> int:
        return len(self._voices)

    # --- rendering (called from the audio thread) ---

    def _apply_events(self) -> None:
        while True:
            try:
                kind, channel, *rest = self._events.get_nowait()
            except queue.Empty:
                return
            if kind == "on":
                note, velocity = rest
                self._release(lambda v: v.channel == channel and v.note == note)
                if len(self._voices) >= self.max_voices:
                    released = [v for v in self._voices if v.released]
                    self._voices.remove(released[0] if released else self._voices[0])
                self._voices.append(_Voice(channel, note, velocity))
            elif kind == "off":
                (note,) = rest
                self._release(lambda v: v.channel == channel and v.note == note)
            elif kind == "all_off":
                self._release(lambda v: v.channel == channel)

    def _release(self, match) -> None:
        for v in self._voices:
            if match(v):
                v.release()

    def _channel_gain_ramps(self, frames: int) -> list[np.ndarray | float]:
        """Per channel: the mix level for this block, gliding towards its target."""
        max_step = frames / (self.sample_rate * _GAIN_GLIDE)
        ramps: list[np.ndarray | float] = []
        for ch, target in enumerate(self.channel_gains):
            start = self._channel_gain_now[ch]
            if start == target:
                ramps.append(start)
                continue
            end = start + min(max_step, max(-max_step, target - start))
            ramps.append(np.linspace(start, end, frames))
            self._channel_gain_now[ch] = end
        return ramps

    def render(self, frames: int) -> np.ndarray:
        self._apply_events()
        gains = self._channel_gain_ramps(frames)
        channels: dict[int, np.ndarray] = {}
        for v in self._voices:
            p = self._channel_params[v.channel]
            env = v.envelope(frames, p, self.sample_rate)
            out = channels.setdefault(v.channel, np.zeros(frames))
            out += v.oscillator(frames, p["waveform"], self.sample_rate) * env * (v.amp * p["volume"])
        mix = np.zeros(frames)
        for ch, out in channels.items():
            p = self._channel_params[ch]
            mix += self._eqs[ch].process(out, p["eq_low"], p["eq_mid"], p["eq_high"]) * gains[ch]
        self._voices = [v for v in self._voices if not v.done]

        # Keep chords about as loud as single notes, gliding to avoid clicks.
        target = _VOICE_LEVEL / math.sqrt(max(1, len(self._voices)))
        mix *= np.linspace(self._gain, target, frames)
        self._gain = target
        return np.tanh(mix).astype(np.float32)

    def _callback(self, outdata, frames, _time, _status) -> None:
        outdata[:] = self.render(frames)[:, None]

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=2,
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
