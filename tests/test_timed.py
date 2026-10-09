import pytest

from musicjammer.audio import METRONOME_CHANNEL
from musicjammer.game import DuelConfig, Side
from musicjammer.session import Phase, TimedSession
from musicjammer.theory import MAJOR, Key, RuleSet

from .test_session import CHORDS, ScriptedBot, SilentEngine

A, B, C = 9, 11, 0
BPM = 120  # 0.5 s beats, 2 s bars


class ClickCounter(SilentEngine):
    def __init__(self):
        super().__init__()
        self.clicks = []

    def note_on(self, channel, note, velocity=100):
        super().note_on(channel, note, velocity)
        if channel == METRONOME_CHANNEL:
            self.clicks.append(note)


def start(bot_moves, bars=4, metronome=True, **config):
    config.setdefault("rules", RuleSet(repeat_window=4))
    config.setdefault("cadence_rule", "dominant")
    engine = ClickCounter()
    session = TimedSession(DuelConfig(Key(0, MAJOR), bars=bars, **config), engine, ScriptedBot(bot_moves),
                           now=0.0, bpm=BPM, metronome=metronome)
    return session, engine


def hold(session, root, type_id, now):
    session.select_type(type_id, now)
    session.press_root(root, now)


def test_count_in_then_the_bot_plays_on_the_downbeat():
    session, engine = start(["F", "Em"])
    assert session.phase is Phase.COUNT_IN
    assert [session.count_in(t) for t in (0.0, 0.6, 1.2, 1.9)] == [4, 3, 2, 1]
    session.update(1.99)
    assert engine.clicks == [84, 77, 77, 77] and not session.blocks
    assert session.bar_label == "count-in"
    session.update(2.0)
    assert session.phase is Phase.BOT_BAR and session.blocks[0].chord == CHORDS["F"]
    assert session.bar_label == "bar 1 / 4"
    assert session.camera_at(2.0) == -1 and session.camera_at(3.0) == -0.5


def test_chord_held_at_the_downbeat_is_played_and_rings_on():
    session, engine = start(["F", "Em"])
    session.update(2.0)
    hold(session, A, "min", 3.0)  # silent preview during the bot's bar
    assert session.preview == CHORDS["Am"] and not any(ch == 0 for ch, n in engine.sounding)
    session.update(4.0)
    assert session.phase is Phase.PLAYER_BAR and session.blocks[-1].chord == CHORDS["Am"]
    session.release_root(A, 4.5)  # letting go doesn't cut the chord
    session.update(5.0)
    assert {n for ch, n in engine.sounding if ch == 0} == {57, 60, 64, 69}
    assert not any(ch == 1 for ch, n in engine.sounding)  # the bot's chord stopped at the downbeat


@pytest.mark.parametrize("press_at, release_at", [(4.1, None), (3.0, 3.95)])
def test_grace_windows(press_at, release_at):
    session, _ = start(["F", "Em"])
    session.update(2.0)
    session.update(4.0)  # nothing held exactly on the downbeat
    if press_at < 4.0:
        session, _ = start(["F", "Em"])
        session.update(2.0)
        hold(session, A, "min", press_at)
        session.release_root(A, release_at)  # let go 50 ms early
        session.update(4.0)
    else:
        hold(session, A, "min", press_at)  # pressed 100 ms late
        session.update(press_at)
    assert session.blocks[-1].chord == CHORDS["Am"]


def test_nothing_held_or_illegal_is_a_miss():
    session, _ = start(["F", "Dm", "Am"], bars=6)
    session.update(2.0)
    session.update(4.0)
    session.update(4.2)  # past the grace window
    assert session.blocks[-1].chord is None and "miss" in session.current_message(4.2)
    session.update(6.0)
    hold(session, 6, "maj", 7.0)  # F# after Dm: no common notes
    session.update(8.0)
    session.update(8.2)
    assert session.blocks[-1].side is Side.PLAYER and session.blocks[-1].chord is None
    assert session.current_message(8.2).startswith("F#: not enough common notes")


def test_shift_at_the_downbeat_plays_the_joker():
    session, _ = start(["F", "Em"])
    session.update(2.0)
    hold(session, 6, "maj", 3.0)  # F#: illegal after F without the joker
    session.joker_held = True
    session.update(4.0)
    assert session.blocks[-1].chord == CHORDS["F#"] and session.blocks[-1].joker
    assert session.round.jokers_left[Side.PLAYER] == 0


def test_round_ends_after_the_last_bar():
    session, engine = start(["F", "Em"], bars=2, metronome=False)
    session.update(2.0)
    hold(session, A, "min", 3.0)
    session.update(4.0)
    assert session.phase is Phase.PLAYER_BAR
    session.update(6.0)
    assert session.phase is Phase.ROUND_OVER and session.result
    assert engine.clicks == [84, 77, 77, 77]  # only the count-in when the metronome is off
    assert not any(ch in (0, 1) for ch, n in engine.sounding)
