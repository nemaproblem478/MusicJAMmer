"""Which chords are legal answers to the previous one."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import permutations

from .chords import CHORD_TYPES, Chord, ChordType
from .distance import anchor_position
from .notes import circle_steps


class MoveError(Enum):
    NO_COMMON_TONES = "not enough common notes with the previous chord"
    TOO_FAR = "the voices move too far from the previous chord"
    TOO_FAR_ON_CIRCLE = "too many steps around the circle of fifths from the previous chord"
    NO_JOKERS = "no jokers left"
    REPEATED = "this chord was played too recently"


@dataclass(frozen=True)
class RuleSet:
    min_common_tones: int = 1
    max_voice_leading: int | None = None  # max total semitones the voices may move, None = no limit
    max_circle_steps: int | None = 1  # max circle-of-fifths steps between anchors, None = no limit
    repeat_window: int = 8  # a chord can't repeat any of the last N chords (both players)


def common_tones(a: Chord, b: Chord) -> int:
    return len(a.pitch_classes & b.pitch_classes)


def _semitones(x: int, y: int) -> int:
    d = abs(x - y) % 12
    return min(d, 12 - d)


def voice_leading(a: Chord, b: Chord) -> int:
    """Smallest total number of semitones the voices move to get from one core to the other.

    Notes of the bigger chord left without a partner move to their nearest note.
    """
    small, big = sorted((sorted(a.pitch_classes), sorted(b.pitch_classes)), key=len)
    best = None
    for chosen in permutations(big, len(small)):
        cost = sum(_semitones(x, y) for x, y in zip(small, chosen))
        cost += sum(min(_semitones(x, y) for y in small) for x in big if x not in chosen)
        best = cost if best is None else min(best, cost)
    return best


def connection_error(previous: Chord, chord: Chord, rules: RuleSet) -> MoveError | None:
    """Whether `chord` may follow `previous`, ignoring the repeat ban."""
    if common_tones(chord, previous) < rules.min_common_tones:
        return MoveError.NO_COMMON_TONES
    if rules.max_voice_leading is not None and voice_leading(previous, chord) > rules.max_voice_leading:
        return MoveError.TOO_FAR
    if (
        rules.max_circle_steps is not None
        and circle_steps(anchor_position(previous), anchor_position(chord)) > rules.max_circle_steps
    ):
        return MoveError.TOO_FAR_ON_CIRCLE
    return None


def check_move(
    chord: Chord,
    history: Sequence[Chord],
    rules: RuleSet,
    previous: Chord | None = None,
    joker: bool = False,
) -> MoveError | None:
    """Return why the chord is not a legal answer, or None if it is.

    `history` is every chord played so far in the round, oldest first. `previous`
    is the chord to connect to; it defaults to the last chord of the history (the
    round passes the tonic before the first move). A joker skips the connection
    rules; the repeat ban still applies.
    """
    if previous is None and history:
        previous = history[-1]
    if previous is not None and not joker:
        error = connection_error(previous, chord, rules)
        if error is not None:
            return error
    if rules.repeat_window > 0:
        recent = {c.core for c in history[-rules.repeat_window :]}
        if chord.core in recent:
            return MoveError.REPEATED
    return None


def all_cores(chord_types: Iterable[ChordType] | None = None) -> list[Chord]:
    types = list(CHORD_TYPES.values()) if chord_types is None else list(chord_types)
    return [Chord(root, t) for t in types for root in range(12)]


def legal_moves(
    history: Sequence[Chord],
    rules: RuleSet,
    chord_types: Iterable[ChordType] | None = None,
    previous: Chord | None = None,
) -> list[Chord]:
    return [c for c in all_cores(chord_types) if check_move(c, history, rules, previous) is None]
