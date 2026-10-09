from musicjammer.ai import PENDING, Move
from musicjammer.audio import NoteEngine
from musicjammer.game import DuelConfig, Side
from musicjammer.session import JamSession, Phase
from musicjammer.theory import MAJOR, Chord, Key, MoveError, RuleSet, all_cores

CHORDS = {c.name: c for c in all_cores()}
C, E, A, B = 0, 4, 9, 11


class SilentEngine(NoteEngine):
    def __init__(self):
        super().__init__()
        self.sounding = set()

    @classmethod
    def params(cls):
        return []

    def note_on(self, channel, note, velocity=100):
        self.sounding.add((channel, note))

    def note_off(self, channel, note):
        self.sounding.discard((channel, note))

    def all_notes_off(self, channel):
        self.sounding = {s for s in self.sounding if s[0] != channel}

    def start(self):
        pass

    def stop(self):
        pass


class ScriptedBot:
    """Plays the given chord names in order; None means a miss."""

    def __init__(self, names):
        self.moves = [None if n is None else Move(CHORDS[n]) for n in names]
        self.pending = PENDING
        self.submitted = 0

    def submit(self, game):
        self.pending = self.moves[self.submitted]
        self.submitted += 1

    def poll(self):
        result, self.pending = self.pending, PENDING
        return result

    def close(self):
        pass


def start(bot_moves, bars=8, **config):
    config.setdefault("rules", RuleSet(repeat_window=4))
    config.setdefault("cadence_rule", "dominant")
    engine = SilentEngine()
    session = JamSession(DuelConfig(Key(0, MAJOR), bars=bars, **config), engine, ScriptedBot(bot_moves), now=0.0,
                         ring=1.0, show=0.5)
    return session, engine


def hold(session, root, type_id, now):
    session.select_type(type_id, now)
    session.press_root(root, now)


def test_turn_flow():
    session, engine = start(["F", "Em"])
    assert session.phase is Phase.BOT_THINKING
    session.update(0.0)
    assert session.phase is Phase.BOT_SHOWING and session.blocks[-1].chord == CHORDS["F"]
    assert session.camera_target == -1  # the bot's chord is shown in the right-hand slot first
    session.update(0.6)
    assert session.phase is Phase.PLAYER_TURN and session.camera_target == 0

    hold(session, A, "min", 1.0)
    session.update(2.0)
    assert {n for ch, n in engine.sounding if ch == 0} == {57, 60, 64, 69}  # Am previewed, strummed
    assert any(ch == 1 for ch, n in engine.sounding)  # the bot's F keeps sounding meanwhile

    assert session.confirm(2.0) is None
    assert session.blocks[-1].chord == CHORDS["Am"] and session.camera_target == 1
    assert not any(ch == 1 for ch, n in engine.sounding)  # the bot's chord stops
    session.update(2.5)
    assert session.phase is Phase.BOT_THINKING  # the player's chord still rings
    session.update(3.0)
    assert session.phase is Phase.BOT_SHOWING and session.blocks[-1].chord == CHORDS["Em"]
    assert not any(ch == 0 for ch, n in engine.sounding)


def test_mix_levels_during_the_players_turn():
    engine = SilentEngine()
    session = JamSession(DuelConfig(Key(0, MAJOR), bars=8, rules=RuleSet(repeat_window=4)), engine,
                         ScriptedBot(["F", "Em"]), now=0.0, ring=1.0, show=0.5, preview_gain=0.4, bot_gain=0.0)
    session.update(0.0)
    assert engine.channel_gains[:2] == [1.0, 1.0]  # the bot's chord arrives at full level
    session.update(0.6)
    assert engine.channel_gains[:2] == [0.4, 0.0]  # quiet preview, bot muted while you choose
    hold(session, A, "min", 1.0)
    session.confirm(1.0)
    assert engine.channel_gains[0] == 1.0  # the confirmed chord swells to full
    session.update(2.0)
    assert engine.channel_gains[:2] == [1.0, 1.0]
    session.close()


def test_illegal_chord_is_refused_with_a_reason():
    session, _ = start(["F", None])
    session.update(0.0)
    session.update(0.6)
    hold(session, 6, "maj", 1.0)  # F#: nothing in common with F
    assert session.preview_error() is MoveError.NO_COMMON_TONES
    assert session.confirm(1.0) is MoveError.NO_COMMON_TONES
    assert "joker" in session.current_message(1.0)
    assert session.phase is Phase.PLAYER_TURN and len(session.blocks) == 1
    assert session.confirm(1.0, joker=True) is None  # but the joker lets it through
    assert session.blocks[-1].joker and session.round.jokers_left[Side.PLAYER] == 0


def test_cadence_trap_end_to_end():
    session, _ = start(["F", "Em", "D", "G"], bars=8)
    now = 0.0
    for root, kind in ((A, "min"), (B, "min"), (B, "dim")):
        session.update(now)
        now += 0.6
        session.update(now)
        assert session.phase is Phase.PLAYER_TURN
        hold(session, root, kind, now)
        assert session.confirm(now) is None
        session.release_root(root, now)
        now += 1.0
    session.update(now)  # the bot is forced onto G
    assert session.blocks[-1].chord == CHORDS["G"]
    session.update(now + 0.6)
    assert session.cadence_available and session.round.pot == 8
    hold(session, C, "maj", now + 1)
    assert session.preview_is_cadence()
    session.confirm(now + 1)
    assert session.blocks[-1].cadence and session.round.points[Side.PLAYER] == 8
    assert "Cadence" in session.current_message(now + 1)
    assert session.phase is Phase.ROUND_OVER and session.result.startswith("You win  8 : 0")


def test_bot_miss_and_leading_tone_hints():
    session, _ = start([None], cadence_rule="leading_tone")
    session.update(0.0)
    assert session.blocks[-1].chord is None and "misses" in session.current_message(0.0)
    session.update(0.6)
    assert session.phase is Phase.PLAYER_TURN
    assert session.danger_pitch_classes == {5}  # F is the leading tone of F# major
    assert session.gives_bot_a_cadence(CHORDS["Dm"]) and not session.gives_bot_a_cadence(CHORDS["Am"])
