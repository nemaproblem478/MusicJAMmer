import numpy as np
import pytest

from musicjammer.audio import BOT_CHANNEL, PLAYER_CHANNEL, ChordPerformer, NoteEngine, NumpySynth
from musicjammer.theory import MAJ, MAJOR_SEVENTH, MIN, SEVENTH, Chord

SR = 44100


def render_seconds(synth: NumpySynth, seconds: float) -> np.ndarray:
    blocks = int(seconds * SR / synth.block_size) + 1
    return np.concatenate([synth.render(synth.block_size) for _ in range(blocks)])


@pytest.mark.parametrize("waveform", ["sine", "triangle", "saw", "square"])
def test_note_sounds_while_held_and_dies_after_release(waveform):
    synth = NumpySynth(SR)
    synth.set_param(PLAYER_CHANNEL, "waveform", waveform)
    synth.set_param(PLAYER_CHANNEL, "release", 0.05)
    synth.note_on(PLAYER_CHANNEL, 60)
    held = render_seconds(synth, 1.0)
    assert np.abs(held[-SR // 10 :]).max() > 0.05  # still sustaining after a second
    synth.note_off(PLAYER_CHANNEL, 60)
    render_seconds(synth, 0.1)
    assert synth.active_voices == 0
    assert np.abs(synth.render(256)).max() == 0.0


def test_output_stays_in_range_with_many_voices():
    synth = NumpySynth(SR)
    synth.set_param(PLAYER_CHANNEL, "waveform", "square")
    for note in range(48, 72):
        synth.note_on(PLAYER_CHANNEL, note, 127)
    out = render_seconds(synth, 0.5)
    assert np.abs(out).max() <= 1.0
    assert synth.active_voices == 24


def test_voice_limit():
    synth = NumpySynth(SR, max_voices=4)
    for note in range(60, 70):
        synth.note_on(PLAYER_CHANNEL, note)
    synth.render(256)
    assert synth.active_voices == 4


def test_all_notes_off_only_touches_its_channel():
    synth = NumpySynth(SR)
    for ch in (PLAYER_CHANNEL, BOT_CHANNEL):
        synth.set_param(ch, "release", 0.01)
        synth.note_on(ch, 60)
    synth.render(256)
    synth.all_notes_off(PLAYER_CHANNEL)
    render_seconds(synth, 0.05)
    assert synth.active_voices == 1


def test_params_are_clamped_and_validated():
    synth = NumpySynth(SR)
    synth.set_param(PLAYER_CHANNEL, "attack", 99)
    assert synth.get_param(PLAYER_CHANNEL, "attack") == 2.0
    with pytest.raises(ValueError):
        synth.set_param(PLAYER_CHANNEL, "waveform", "noise")
    synth.copy_params(PLAYER_CHANNEL, BOT_CHANNEL)
    assert synth.get_param(BOT_CHANNEL, "attack") == 2.0


def test_channel_gain_glides_and_only_affects_its_channel():
    synth = NumpySynth(SR)
    for ch in (PLAYER_CHANNEL, BOT_CHANNEL):
        synth.set_param(ch, "waveform", "sine")
        synth.set_param(ch, "attack", 0.001)
        synth.set_param(ch, "sustain", 1.0)
    synth.note_on(PLAYER_CHANNEL, 69)
    loud = np.abs(render_seconds(synth, 0.3)[-2048:]).max()
    synth.set_channel_gain(PLAYER_CHANNEL, 0.25)
    first_block = synth.render(256)
    assert np.abs(first_block).max() > 0.9 * loud  # no jump: it glides
    quiet = np.abs(render_seconds(synth, 0.3)[-2048:]).max()
    assert quiet < 0.4 * loud
    synth.note_on(BOT_CHANNEL, 81)
    synth.note_off(PLAYER_CHANNEL, 69)
    render_seconds(synth, 1.0)
    bot = np.abs(render_seconds(synth, 0.2)).max()
    assert bot > 0.9 * loud  # the bot's channel kept full level


def test_shortening_a_stage_mid_note_does_not_hang():
    synth = NumpySynth(SR)
    synth.set_param(PLAYER_CHANNEL, "attack", 1.0)
    synth.note_on(PLAYER_CHANNEL, 60)
    render_seconds(synth, 0.5)
    synth.set_param(PLAYER_CHANNEL, "attack", 0.01)
    render_seconds(synth, 0.1)


class FakeEngine(NoteEngine):
    def __init__(self):
        super().__init__()
        self.log = []

    @classmethod
    def params(cls):
        return []

    def note_on(self, channel, note, velocity=100):
        self.log.append(("on", note))

    def note_off(self, channel, note):
        self.log.append(("off", note))

    def all_notes_off(self, channel):
        self.log.append(("all_off",))

    def start(self):
        pass

    def stop(self):
        pass


def test_performer_strums_upwards():
    engine = FakeEngine()
    p = ChordPerformer(engine, PLAYER_CHANNEL, base_note=48, strum=0.1)
    p.play(Chord(0, MAJ), now=0.0)
    assert engine.log == [("on", 48)]
    p.update(0.15)
    assert engine.log[-1] == ("on", 52)
    p.update(1.0)
    assert engine.log[1:] == [("on", 52), ("on", 55), ("on", 60)]
    assert p.sounding == {48, 52, 55, 60}


def test_performer_keeps_root_when_type_changes():
    engine = FakeEngine()
    p = ChordPerformer(engine, PLAYER_CHANNEL, base_note=48, strum=0.1)
    p.play(Chord(0, MAJ), 0.0)
    p.update(1.0)
    engine.log.clear()
    p.play(Chord(0, MIN), 1.0)
    assert ("off", 48) not in engine.log and ("on", 48) not in engine.log
    assert sorted(engine.log) == [("off", 52), ("off", 55), ("off", 60)]
    p.update(2.0)
    assert engine.log[3:] == [("on", 51), ("on", 55), ("on", 60)]


def test_performer_cancels_pending_notes_on_stop():
    engine = FakeEngine()
    p = ChordPerformer(engine, PLAYER_CHANNEL, strum=0.1)
    p.play(Chord(0, MAJ), 0.0)
    p.stop()
    p.update(1.0)
    assert [e for e in engine.log if e[0] == "on"] == [("on", 48)]
    assert p.sounding == set()


def test_performer_swaps_only_the_fourth_note_on_extension_change():
    engine = FakeEngine()
    p = ChordPerformer(engine, PLAYER_CHANNEL, base_note=48, strum=0.1)
    p.play(Chord(0, MAJ), 0.0)
    p.update(1.0)
    engine.log.clear()
    p.play(Chord(0, MAJ, SEVENTH), 1.0)  # C -> C7: octave C off, Bb on, nothing else touched
    assert engine.log == [("off", 60), ("on", 58)]
    assert p.sounding == {48, 52, 55, 58}


def test_extension_change_mid_strum_keeps_the_strum_going():
    engine = FakeEngine()
    p = ChordPerformer(engine, PLAYER_CHANNEL, base_note=48, strum=0.1)
    p.play(Chord(0, MAJ), 0.0)
    p.update(0.15)  # only C and E so far
    p.play(Chord(0, MAJ, MAJOR_SEVENTH), 0.15)  # B on now; octave C never comes
    p.update(1.0)
    assert [e for e in engine.log if e[0] == "on"] == [("on", 48), ("on", 52), ("on", 59), ("on", 55)]
    assert p.sounding == {48, 52, 55, 59}


def _level(synth, channel, note, seconds=0.4):
    synth.note_on(channel, note)
    out = render_seconds(synth, seconds)
    synth.note_off(channel, note)
    render_seconds(synth, 1.0)
    return np.abs(out[-4096:]).max()


@pytest.mark.parametrize("band, low_note, high_note", [("eq_low", 33, 105), ("eq_high", 117, 33)])
def test_eq_shapes_only_its_band(band, low_note, high_note):
    """`low_note` sits inside the band (55 Hz / 7 kHz), `high_note` far outside it."""
    def measure(gain):
        synth = NumpySynth(SR)
        synth.set_param(PLAYER_CHANNEL, "waveform", "sine")
        synth.set_param(PLAYER_CHANNEL, "sustain", 1.0)
        synth.set_param(PLAYER_CHANNEL, "release", 0.01)
        synth.set_param(PLAYER_CHANNEL, band, gain)
        return _level(synth, PLAYER_CHANNEL, low_note), _level(synth, PLAYER_CHANNEL, high_note)

    flat_in, flat_out = measure(0.0)
    cut_in, cut_out = measure(-12.0)
    assert cut_in < 0.45 * flat_in  # about -9 dB or more inside the band
    assert cut_out == pytest.approx(flat_out, rel=0.08)  # untouched far away


def test_flat_eq_is_transparent():
    a, b = NumpySynth(SR), NumpySynth(SR)
    b.set_param(PLAYER_CHANNEL, "eq_mid", 6.0)
    b.set_param(PLAYER_CHANNEL, "eq_mid", 0.0)  # back to flat
    for synth in (a, b):
        synth.note_on(PLAYER_CHANNEL, 60)
    assert np.allclose(render_seconds(a, 0.2), render_seconds(b, 0.2))


@pytest.mark.parametrize("band, note", [("eq_low", 45), ("eq_mid", 84), ("eq_high", 108)])
@pytest.mark.parametrize("how", ["step", "jump"])
def test_turning_an_eq_knob_mid_note_does_not_click(band, note, how):
    """A click is a burst of high frequencies: the second difference of a sine jumps far above its steady size."""
    synth = NumpySynth(SR)
    synth.set_param(PLAYER_CHANNEL, "waveform", "sine")
    synth.set_param(PLAYER_CHANNEL, "sustain", 1.0)
    synth.set_param(PLAYER_CHANNEL, band, -12.0)
    synth.note_on(PLAYER_CHANNEL, note)
    render_seconds(synth, 0.3)
    if how == "step":  # Up held on the keyboard: 0.6 dB every few blocks
        parts = []
        for k in range(41):
            synth.set_param(PLAYER_CHANNEL, band, -12.0 + 0.6 * k)
            parts.append(np.concatenate([synth.render(256) for _ in range(3)]))
        turning = np.concatenate(parts)
    else:  # a fast drag from one end to the other
        synth.set_param(PLAYER_CHANNEL, band, 12.0)
        turning = render_seconds(synth, 0.4)
    steady = render_seconds(synth, 0.3)  # the same note, settled at +12 dB
    spike = np.abs(np.diff(turning, 2)).max() / np.abs(np.diff(steady, 2)).max()
    assert spike < 1.5  # resetting the filters on every step used to give ~3000x on the low band


def test_block_biquad_matches_a_plain_sample_by_sample_filter():
    """The numpy block filter must equal the textbook recursion, across block boundaries."""
    from musicjammer.audio.eq import ChannelEQ, band_filters

    rng = np.random.default_rng(0)
    signal = rng.standard_normal(256 * 6)
    gains = (6.0, -4.0, 9.0)
    expected = signal.copy()
    for b, a in band_filters(*gains, SR):
        z1 = z2 = 0.0
        out = np.empty_like(expected)
        for i, x in enumerate(expected):
            y = b[0] * x + z1
            z1, z2 = b[1] * x - a[1] * y + z2, b[2] * x - a[2] * y
            out[i] = y
        expected = out
    eq = ChannelEQ(SR)
    eq._gains = list(gains)  # skip the glide
    got = np.concatenate([eq.process(signal[i : i + 256], *gains) for i in range(0, len(signal), 256)])
    assert np.allclose(got, expected, atol=1e-9)
