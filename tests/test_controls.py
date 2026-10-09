from musicjammer.controls import ChordInput, Confirm, ExtensionKey, RootKey, TypeKey, build_keymap
from musicjammer.controls.keymap import digit, letter
from musicjammer.theory import DIM, MIN, Chord


def test_keymap_layout():
    keymap = build_keymap()
    assert keymap[letter("A")] == RootKey(0)
    assert keymap[letter("W")] == RootKey(1)
    assert keymap[letter("J")] == RootKey(11)
    assert keymap[letter("Z")] == TypeKey("maj")
    assert keymap[letter("X")] == TypeKey("min")
    assert keymap[letter("C")] == TypeKey("dim")
    assert keymap[digit("6")] == ExtensionKey("6")
    assert keymap[digit("7")] == ExtensionKey("b7")
    assert keymap[digit("8")] == ExtensionKey("maj7")
    assert keymap[digit("9")] == ExtensionKey("add9")
    assert keymap[40] == Confirm()


def test_no_chord_without_a_root():
    ci = ChordInput()
    assert ci.chord is None
    ci.select_type("min")
    assert ci.chord is None


def test_type_and_extension_latch_across_roots():
    ci = ChordInput()
    ci.select_type("min")
    ci.toggle_extension("b7")
    assert ci.press_root(9)
    assert ci.chord.name == "Am7"
    ci.release_root(9)
    ci.press_root(2)
    assert ci.chord.name == "Dm7"
    assert ci.toggle_extension("b7")
    assert ci.chord.name == "Dm"


def test_unsupported_extension_is_kept_but_ignored():
    ci = ChordInput()
    ci.press_root(11)
    ci.toggle_extension("maj7")
    ci.select_type("dim")
    assert ci.chord == Chord(11, DIM)
    ci.select_type("min")
    assert ci.chord.name == "Bm(maj7)"


def test_latest_held_root_wins_and_falls_back():
    ci = ChordInput()
    ci.press_root(0)
    ci.press_root(7)
    assert ci.root == 7
    assert ci.release_root(7)
    assert ci.root == 0
    assert not ci.release_root(5)  # wasn't held
    assert ci.release_root(0)
    assert ci.chord is None


def test_reselecting_same_type_is_not_a_change():
    ci = ChordInput()
    ci.press_root(0)
    ci.select_type("min")
    assert not ci.select_type("min")
    assert ci.chord == Chord(0, MIN)
