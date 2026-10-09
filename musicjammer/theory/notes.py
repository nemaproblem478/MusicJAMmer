"""Pitch classes and the circle of fifths."""

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(pitch_class: int) -> str:
    return NOTE_NAMES[pitch_class % 12]


def fifths_position(pitch_class: int) -> int:
    """Position on the circle of fifths, clockwise from C (C=0, G=1, D=2, ..., F=11)."""
    return (pitch_class * 7) % 12


def circle_steps(position_a: int, position_b: int) -> int:
    """Shortest number of steps between two circle-of-fifths positions (0..6)."""
    d = (position_a - position_b) % 12
    return min(d, 12 - d)
