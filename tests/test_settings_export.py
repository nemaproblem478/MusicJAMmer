import json

import mido

from musicjammer.audio import BOT_CHANNEL, PLAYER_CHANNEL, NumpySynth
from musicjammer.export import jam_to_midi, save_jam
from musicjammer.game import DuelConfig, Side
from musicjammer.session import Block
from musicjammer.settings import GameSettings, SettingsStore
from musicjammer.theory import MAJ, MAJOR, MIN, SEVENTH, Chord, Key


def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    engine = NumpySynth()
    store = SettingsStore(engine, path)
    store.game = GameSettings(tonic=9, mode="minor", difficulty="hard", bars=8, timed=True, bpm=120)
    engine.set_param(PLAYER_CHANNEL, "waveform", "saw")
    engine.set_param(PLAYER_CHANNEL, "attack", 0.5)
    engine.set_param(BOT_CHANNEL, "waveform", "square")
    store.bot_linked = False
    store.save()

    fresh = NumpySynth()
    loaded = SettingsStore(fresh, path)
    loaded.load()
    assert loaded.game == store.game
    assert fresh.get_param(PLAYER_CHANNEL, "waveform") == "saw"
    assert fresh.get_param(PLAYER_CHANNEL, "attack") == 0.5
    assert fresh.get_param(BOT_CHANNEL, "waveform") == "square" and not loaded.bot_linked


def test_linked_bot_copies_the_player(tmp_path):
    engine = NumpySynth()
    store = SettingsStore(engine, tmp_path / "s.json")
    engine.set_param(PLAYER_CHANNEL, "waveform", "sine")
    store.sync_bot()
    assert engine.get_param(BOT_CHANNEL, "waveform") == "sine"


def test_bad_files_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    for content in ("not json", "[1, 2]", json.dumps({
        "game": {"tonic": 40, "mode": "lydian?", "bars": 7, "bpm": 999, "unknown": 1, "difficulty": "hard"},
        "synth": {"player": {"waveform": "noise", "attack": "slow", "volume": 0.5, "bogus": 3}},
    })):
        path.write_text(content)
        engine = NumpySynth()
        store = SettingsStore(engine, path)
        store.load()
        assert store.game.tonic == 0 and store.game.mode == "major" and store.game.bars == 16
        assert store.game.bpm == 90
        assert engine.get_param(PLAYER_CHANNEL, "waveform") == "triangle"
    assert store.game.difficulty == "hard"  # the valid part survives
    assert engine.get_param(PLAYER_CHANNEL, "volume") == 0.5


def test_missing_file_is_fine(tmp_path):
    store = SettingsStore(NumpySynth(), tmp_path / "nope" / "settings.json")
    store.load()
    assert store.game == GameSettings()
    store.save()
    assert (tmp_path / "nope" / "settings.json").exists()


def test_midi_export(tmp_path):
    config = DuelConfig(Key(0, MAJOR), bars=4)
    blocks = [
        Block(Side.BOT, Chord(4, MIN)),
        Block(Side.PLAYER, Chord(0, MAJ, SEVENTH)),
        Block(Side.BOT, None),  # a missed bar is a rest
        Block(Side.PLAYER, Chord(9, MIN)),
    ]
    path = save_jam(blocks, config, bpm=120, directory=tmp_path)
    midi = mido.MidiFile(path)
    assert len(midi.tracks) == 3 and midi.ticks_per_beat == 480
    assert midi.length == 8.0  # four 2-second bars at 120 BPM

    def notes(track):
        t, out = 0, []
        for m in track:
            t += m.time
            if m.type == "note_on":
                out.append((t, m.channel, m.note))
        return out

    you, bot = notes(midi.tracks[1]), notes(midi.tracks[2])
    assert [n for _, _, n in you] == [48, 52, 55, 58, 57, 60, 64, 69]  # C7 then Am
    assert you[0][0] == 1920 and you[1][0] == 1920 + 58  # bar 2, strummed by ~60 ms
    assert {c for _, c, _ in you} == {PLAYER_CHANNEL} and {c for _, c, _ in bot} == {BOT_CHANNEL}
    assert [n for _, _, n in bot] == [52, 55, 59, 64]  # only Em: the missed bar is silent


def test_knob_maths():
    import pytest

    from musicjammer.ui.knobs import format_value, from_norm, nudge, to_norm

    params = {p.id: p for p in NumpySynth.params()}
    attack, sustain, wave = params["attack"], params["sustain"], params["waveform"]
    for value in (0.001, 0.01, 0.3, 2.0):
        assert from_norm(attack, to_norm(attack, value)) == pytest.approx(value)
    assert to_norm(attack, 0.001) == 0 and to_norm(attack, 2.0) == pytest.approx(1)
    assert from_norm(attack, 2) == 2.0  # clamped
    assert nudge(sustain, 0.5, 4) == pytest.approx(0.6)
    assert nudge(wave, "saw", 1) == "square" and nudge(wave, "sine", -1) == "square"
    assert format_value(attack, 0.012) == "12 ms" and format_value(attack, 1.5) == "1.50 s"
    assert format_value(sustain, 0.7) == "70%"
