"""How far a chord is from the tonic of a key.

    d = 2 * (circle-of-fifths steps from the chord's anchor to the key, 0..6)
      + 1 if the chord's quality differs from the mode's quality
      + the chord type's tension

The anchor is the circle position the chord type borrows (see ChordType.anchor).
Extensions don't affect the distance.
"""

from .chords import Chord
from .keys import Key
from .notes import circle_steps, fifths_position


def anchor_position(chord: Chord) -> int:
    return fifths_position(chord.root + chord.type.anchor)


def distance(chord: Chord, key: Key) -> int:
    steps = circle_steps(anchor_position(chord), key.circle_position)
    mismatch = int(chord.type.quality != key.mode.quality)
    return 2 * steps + mismatch + chord.type.tension
