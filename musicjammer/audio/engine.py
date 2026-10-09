"""The interface every sound backend implements.

The game only speaks MIDI-style events (note on / note off per channel). Each
backend describes its own tweakable parameters with `Param`, so the synth
settings page can build its knobs from that list without knowing the backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

PLAYER_CHANNEL = 0
BOT_CHANNEL = 1
METRONOME_CHANNEL = 9


@dataclass(frozen=True)
class Param:
    id: str
    label: str
    default: float | str
    min: float = 0.0
    max: float = 1.0
    unit: str = ""
    log: bool = False  # knob moves on a logarithmic scale (times, frequencies)
    choices: tuple[str, ...] | None = None
    group: str = ""  # params in the same group sit together on the sound page

    @property
    def is_choice(self) -> bool:
        return self.choices is not None

    def coerce(self, value: float | str) -> float | str:
        if self.is_choice:
            if value not in self.choices:
                raise ValueError(f"{self.id}: {value!r} is not one of {self.choices}")
            return value
        return min(self.max, max(self.min, float(value)))


class NoteEngine(ABC):
    NUM_CHANNELS = 16

    def __init__(self) -> None:
        self._channel_params: list[dict[str, float | str]] = [
            {p.id: p.default for p in self.params()} for _ in range(self.NUM_CHANNELS)
        ]
        # Mix level per channel, set by the game (e.g. a quieter preview), separate from the
        # synth's own volume knob. Backends should glide to a new level rather than jump.
        self.channel_gains = [1.0] * self.NUM_CHANNELS

    @classmethod
    @abstractmethod
    def params(cls) -> list[Param]: ...

    def param(self, param_id: str) -> Param:
        return next(p for p in self.params() if p.id == param_id)

    def get_param(self, channel: int, param_id: str) -> float | str:
        return self._channel_params[channel][param_id]

    def set_param(self, channel: int, param_id: str, value: float | str) -> None:
        self._channel_params[channel][param_id] = self.param(param_id).coerce(value)

    def copy_params(self, src_channel: int, dst_channel: int) -> None:
        self._channel_params[dst_channel] = dict(self._channel_params[src_channel])

    def set_channel_gain(self, channel: int, gain: float) -> None:
        self.channel_gains[channel] = min(1.0, max(0.0, gain))

    @abstractmethod
    def note_on(self, channel: int, note: int, velocity: int = 100) -> None: ...

    @abstractmethod
    def note_off(self, channel: int, note: int) -> None: ...

    @abstractmethod
    def all_notes_off(self, channel: int) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
