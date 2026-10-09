import pytest

from musicjammer.theory import (
    ADD_NINE,
    DIM,
    MAJ,
    MAJOR,
    MAJOR_SEVENTH,
    MIN,
    MINOR,
    SEVENTH,
    SIXTH,
    Chord,
    Key,
    MoveError,
    RuleSet,
    check_move,
    distance,
    legal_moves,
)
from musicjammer.theory.notes import circle_steps, fifths_position

C, D, E, F, G, A, B = 0, 2, 4, 5, 7, 9, 11


def test_fifths_positions():
    assert [fifths_position(pc) for pc in (C, G, D, A, E, B, 6, F)] == [0, 1, 2, 3, 4, 5, 6, 11]
    assert circle_steps(0, 11) == 1
    assert circle_steps(0, 6) == 6


@pytest.mark.parametrize(
    "chord, expected",
    [
        (Chord(C, MAJ), 0),
        (Chord(C, MAJ, MAJOR_SEVENTH), 0),
        (Chord(A, MIN), 1),
        (Chord(A, MIN, SEVENTH), 1),
        (Chord(G, MAJ), 2),
        (Chord(F, MAJ), 2),
        (Chord(D, MIN), 3),
        (Chord(E, MIN), 3),
        (Chord(B, DIM), 3),
        (Chord(6, MAJ), 12),  # F#
        (Chord(3, MIN), 13),  # D#m: its relative major F# is opposite C
    ],
)
def test_distance_in_c_major(chord, expected):
    assert distance(chord, Key(C, MAJOR)) == expected


def test_distance_in_a_minor_mirrors_c_major():
    key = Key(A, MINOR)
    assert distance(Chord(A, MIN), key) == 0
    assert distance(Chord(C, MAJ), key) == 1
    assert key.tonic_chord == Chord(A, MIN)


@pytest.mark.parametrize(
    "chord, name, notes",
    [
        (Chord(C, MAJ), "C", [48, 52, 55, 60]),
        (Chord(C, MIN), "Cm", [48, 51, 55, 60]),
        (Chord(C, MAJ, SIXTH), "C6", [48, 52, 55, 57]),
        (Chord(G, MAJ, SEVENTH), "G7", [55, 59, 62, 65]),
        (Chord(C, MAJ, MAJOR_SEVENTH), "Cmaj7", [48, 52, 55, 59]),
        (Chord(C, MIN, MAJOR_SEVENTH), "Cm(maj7)", [48, 51, 55, 59]),
        (Chord(C, MAJ, ADD_NINE), "Cadd9", [48, 52, 55, 62]),
        (Chord(B, DIM), "B°", [59, 62, 65, 71]),
        (Chord(B, DIM, SIXTH), "B°7", [59, 62, 65, 68]),
        (Chord(B, DIM, SEVENTH), "Bø7", [59, 62, 65, 69]),
    ],
)
def test_names_and_voicings(chord, name, notes):
    assert chord.name == name
    assert chord.voicing(48) == notes


def test_unavailable_extension_is_rejected():
    with pytest.raises(ValueError):
        Chord(B, DIM, MAJOR_SEVENTH)


def test_extension_does_not_change_the_core():
    assert Chord(C, MAJ, MAJOR_SEVENTH).core == Chord(C, MAJ)
    assert Chord(C, MAJ, ADD_NINE).pitch_classes == Chord(C, MAJ).pitch_classes


def test_move_needs_common_tones():
    rules = RuleSet(min_common_tones=1)
    history = [Chord(C, MAJ)]
    assert check_move(Chord(6, MAJ), history, rules) is MoveError.NO_COMMON_TONES  # F# A# C#
    assert check_move(Chord(E, MIN), history, rules) is None
    strict = RuleSet(min_common_tones=2)
    assert check_move(Chord(D, MIN), history, strict) is MoveError.NO_COMMON_TONES
    assert check_move(Chord(A, MIN), history, strict) is None


def test_extensions_cannot_dodge_the_rules():
    history = [Chord(C, MAJ)]
    # add9 on C would share D with Dm-ish chords, but only the core counts
    assert check_move(Chord(C, MAJ, MAJOR_SEVENTH), history, RuleSet()) is MoveError.REPEATED
    assert check_move(Chord(6, MAJ, ADD_NINE), history, RuleSet()) is MoveError.NO_COMMON_TONES


def test_repeat_window():
    history = [Chord(C, MAJ), Chord(A, MIN), Chord(F, MAJ), Chord(D, MIN), Chord(G, MAJ)]
    rules = RuleSet(min_common_tones=0, max_circle_steps=None, repeat_window=4)
    assert check_move(Chord(A, MIN), history, rules) is MoveError.REPEATED
    assert check_move(Chord(C, MAJ), history, rules) is None  # 5 chords ago
    assert check_move(Chord(C, MAJ), history, RuleSet(0, max_circle_steps=None, repeat_window=0)) is None


def test_there_is_always_a_legal_answer():
    rules = RuleSet()
    for prev in legal_moves([], rules):
        assert legal_moves([prev], rules)
