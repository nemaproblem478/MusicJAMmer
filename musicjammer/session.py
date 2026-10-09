"""One round of the jam: turns, sound and what the screen should show.

Two modes share most of the work (SessionBase):

JamSession, untimed. Starting with the bot:

    BOT_THINKING  the bot searches in the background; the player's last chord
                  keeps ringing for `ring` seconds before the bot may answer
    BOT_SHOWING   the bot's chord sounds in the right-hand slot for `show` seconds,
                  then the roll scrolls it to the left
    PLAYER_TURN   the player previews chords and confirms with Enter; the bot's
                  chord keeps sounding meanwhile. Both play at their own mix
                  levels during this phase (`preview_gain`, `bot_gain`); the
                  confirmed chord swells back to full level
    ROUND_OVER

TimedSession, on a tempo. One count-in bar, then bars alternate bot / player:

    COUNT_IN      four metronome clicks
    BOT_BAR       the bot's chord sounds for the whole bar; meanwhile the player
                  silently gets the next chord ready
    PLAYER_BAR    the chord held at the downbeat is played and sounds to the end
                  of the bar on its own; nothing held, or an illegal chord, is a
                  miss. Shift held at the downbeat plays it as the joker.
    ROUND_OVER

Drawing lives elsewhere; sessions only need a sound engine, a bot with
submit()/poll() and the current time, so they can be tested without a window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .ai import PENDING
from .audio import BOT_CHANNEL, METRONOME_CHANNEL, PLAYER_CHANNEL, ChordPerformer, NoteEngine
from .controls import ChordInput
from .game import DuelConfig, DuelRound, Side, cadence_setups
from .theory import Chord, MoveError, all_cores

PLAYER_RING = 1.6
BOT_SHOW = 0.7
MESSAGE_SECONDS = 3.0
LATE_GRACE = 0.15  # a chord pressed this soon after the downbeat still counts
EARLY_GRACE = 0.10  # so does one released this soon before it
CLICK_NOTES = (84, 77)  # accented first beat, other beats
CLICK_LENGTH = 0.08


class Phase(Enum):
    BOT_THINKING = "bot thinking"
    BOT_SHOWING = "bot showing"
    PLAYER_TURN = "player turn"
    COUNT_IN = "count-in"
    BOT_BAR = "bot bar"
    PLAYER_BAR = "player bar"
    ROUND_OVER = "round over"


@dataclass(frozen=True)
class Block:
    """A bar on the piano roll."""

    side: Side
    chord: Chord | None  # None = missed
    joker: bool = False
    cadence: bool = False
    won: int = 0


class SessionBase:
    timed = False

    def __init__(self, config: DuelConfig, engine: NoteEngine, bot) -> None:
        self.config = config
        self.engine = engine
        self.round = DuelRound(config)
        self.input = ChordInput()
        self.player_voice = ChordPerformer(engine, PLAYER_CHANNEL)
        self.bot_voice = ChordPerformer(engine, BOT_CHANNEL)
        self.bot = bot
        self.blocks: list[Block] = []
        self.message = ""
        self.result = ""  # the verdict once the round is over
        self.phase: Phase
        self._message_until = 0.0
        self._cores = all_cores()
        self._bot_setups = cadence_setups(config.bot_key, config.cadence_rule)

    # --- what the screen shows ---

    @property
    def preview_open(self) -> bool:
        """Whether the player is choosing a chord right now."""
        raise NotImplementedError

    @property
    def preview(self) -> Chord | None:
        return self.input.chord if self.preview_open else None

    @property
    def preview_slot(self) -> int:
        """The bar the previewed chord is for."""
        return len(self.blocks)

    @property
    def bar_label(self) -> str:
        """The bar being played or chosen, for the header."""
        return f"bar {min(len(self.blocks) + 1, self.config.bars)} / {self.config.bars}"

    def preview_error(self, joker: bool = False) -> MoveError | None:
        chord = self.preview
        return None if chord is None else self.round.check(chord, joker)

    def preview_is_cadence(self) -> bool:
        chord = self.preview
        return chord is not None and self.round.is_cadence(chord)

    def gives_bot_a_cadence(self, chord: Chord) -> bool:
        return chord.core in self._bot_setups

    @property
    def danger_pitch_classes(self) -> frozenset[int]:
        """Notes that let the bot resolve after the player's chord (its leading tone)."""
        if self.config.cadence_rule == "leading_tone":
            return frozenset({(self.config.bot_key.tonic + 11) % 12})
        return frozenset()

    @property
    def cadence_available(self) -> bool:
        return self.preview_open and self.round.is_cadence(self.config.key.tonic_chord)

    def current_message(self, now: float) -> str:
        return self.message if now < self._message_until else ""

    # --- player input ---

    def press_root(self, pitch_class: int, now: float) -> None:
        before = self.input.chord
        if self.input.press_root(pitch_class):
            self._input_changed(before, now)

    def release_root(self, pitch_class: int, now: float) -> None:
        before = self.input.chord
        if self.input.release_root(pitch_class):
            self._input_changed(before, now)

    def select_type(self, type_id: str, now: float) -> None:
        before = self.input.chord
        if self.input.select_type(type_id):
            self._input_changed(before, now)

    def toggle_extension(self, extension_id: str, now: float) -> None:
        before = self.input.chord
        if self.input.toggle_extension(extension_id):
            self._input_changed(before, now)

    def release_all(self, now: float) -> None:
        before = self.input.chord
        if self.input.release_all():
            self._input_changed(before, now)

    def _input_changed(self, before: Chord | None, now: float) -> None:
        pass

    # --- shared moves ---

    def _play_bot_move(self, move, now: float) -> None:
        if move is None:
            self._miss(Side.BOT, "The bot has no legal move: it misses the bar", now)
            return
        bar = self.round.play(move.chord, move.joker)
        self.blocks.append(Block(Side.BOT, move.chord, bar.joker, bar.cadence, bar.won))
        self.bot_voice.play(move.chord, now)
        if bar.cadence:
            self._say(f"Bot cadence! The bot takes {bar.won}", now)
        elif bar.joker:
            self._say("The bot played its joker", now)

    def _play_player(self, chord: Chord, joker: bool, now: float) -> None:
        bar = self.round.play(chord, joker)
        self.blocks.append(Block(Side.PLAYER, chord, bar.joker, bar.cadence, bar.won))
        if bar.cadence:
            self._say(f"Cadence! You take {bar.won}", now)
        elif bar.joker:
            self._say("Joker played", now)

    def _miss(self, side: Side, text: str, now: float) -> None:
        self.round.miss()
        self.blocks.append(Block(side, None))
        self._say(text, now)

    def _check(self, chord: Chord, joker: bool) -> tuple[MoveError | None, bool]:
        """(why the chord can't be played, whether it would use the joker)."""
        if self.round.is_cadence(chord):
            return None, False  # a cadence never needs the joker
        return self.round.check(chord, joker), joker

    def _player_can_move(self) -> bool:
        has_joker = self.round.jokers_left[Side.PLAYER] > 0
        return any(
            self.round.check(c) is None or (has_joker and self.round.check(c, joker=True) is None)
            for c in self._cores
        )

    def _set_result(self) -> None:
        self.phase = Phase.ROUND_OVER
        you, bot = self.round.points[Side.PLAYER], self.round.points[Side.BOT]
        verdict = {Side.PLAYER: "You win", Side.BOT: "The bot wins", None: "Draw"}[self.round.winner]
        burnt = self.round.leftover[1] if self.round.leftover else 0
        self.result = f"{verdict}  {you} : {bot}" + (f"   ({burnt} unclaimed points burnt)" if burnt else "")

    def _say(self, text: str, now: float) -> None:
        self.message = text
        self._message_until = now + MESSAGE_SECONDS

    def close(self) -> None:
        self.player_voice.stop()
        self.bot_voice.stop()
        self.engine.set_channel_gain(PLAYER_CHANNEL, 1.0)
        self.engine.set_channel_gain(BOT_CHANNEL, 1.0)
        self.bot.close()


class JamSession(SessionBase):
    """Untimed mode: take as long as you like, Enter to play."""

    def __init__(
        self,
        config: DuelConfig,
        engine: NoteEngine,
        bot,
        now: float,
        ring: float = PLAYER_RING,
        show: float = BOT_SHOW,
        preview_gain: float = 1.0,
        bot_gain: float = 1.0,
    ) -> None:
        super().__init__(config, engine, bot)
        self.ring = ring
        self.show = show
        self.preview_gain = preview_gain
        self.bot_gain = bot_gain
        self.camera_target = -1.0  # slot index shown on the left; -1 is the silent tonic
        self._ready_at = now
        self._show_until = 0.0
        self._ring_until: float | None = None
        self.phase = Phase.BOT_THINKING
        self.bot.submit(self.round)

    @property
    def preview_open(self) -> bool:
        return self.phase is Phase.PLAYER_TURN

    def _input_changed(self, before: Chord | None, now: float) -> None:
        if not self.preview_open:
            return
        chord = self.input.chord
        if chord is None:
            self.player_voice.stop()
        else:
            self.player_voice.play(chord, now)

    def confirm(self, now: float, joker: bool = False) -> MoveError | None:
        """Play the held chord. Returns why it was refused, if it was."""
        if self.phase is not Phase.PLAYER_TURN:
            return None
        chord = self.input.chord
        if chord is None:
            self._say("Hold a root key, then press Enter", now)
            return None
        error, joker = self._check(chord, joker)
        if error is not None:
            hint = ""
            if not joker and error is not MoveError.REPEATED and self.round.jokers_left[Side.PLAYER]:
                hint = " (Shift+Enter plays it as your joker)"
            self._say(f"{chord.name}: {error.value}{hint}", now)
            return error
        self._play_player(chord, joker, now)
        self.bot_voice.stop()
        self.engine.set_channel_gain(PLAYER_CHANNEL, 1.0)
        self.input.release_all()  # the chord rings on by itself; new presses start a new preview
        self._ring_until = now + self.ring
        self._after_player_bar(now + self.ring)
        return None

    def update(self, now: float) -> None:
        self.player_voice.update(now)
        self.bot_voice.update(now)
        if self._ring_until is not None and now >= self._ring_until:
            self._ring_until = None
            self.player_voice.stop()
            if self.phase is Phase.ROUND_OVER:
                self.bot_voice.stop()
        if self.phase is Phase.BOT_THINKING and now >= self._ready_at:
            move = self.bot.poll()
            if move is not PENDING:
                self.player_voice.stop()
                self.engine.set_channel_gain(BOT_CHANNEL, 1.0)
                self._play_bot_move(move, now)
                self.phase = Phase.BOT_SHOWING
                self._show_until = now + self.show
        elif self.phase is Phase.BOT_SHOWING and now >= self._show_until:
            self.camera_target = len(self.blocks) - 1
            if self.round.finished:
                self._finish(now)
            else:
                self._start_player_turn(now)

    def _start_player_turn(self, now: float) -> None:
        self.phase = Phase.PLAYER_TURN
        self.engine.set_channel_gain(PLAYER_CHANNEL, self.preview_gain)
        self.engine.set_channel_gain(BOT_CHANNEL, self.bot_gain)
        if not self._player_can_move():
            self._miss(Side.PLAYER, "No legal move: you miss this bar", now)
            self._after_player_bar(now + self.show)

    def _after_player_bar(self, ready_at: float) -> None:
        self.camera_target = len(self.blocks) - 1
        if self.round.finished:
            self._finish(ready_at)
            return
        self.phase = Phase.BOT_THINKING
        self._ready_at = ready_at
        self.bot.submit(self.round)

    def _finish(self, now: float) -> None:
        self._set_result()
        self._ring_until = max(self._ring_until or 0.0, now + self.ring)  # let the last chord ring out


class TimedSession(SessionBase):
    """Timed mode: the music keeps going at `bpm`, in 4/4."""

    timed = True

    def __init__(
        self,
        config: DuelConfig,
        engine: NoteEngine,
        bot,
        now: float,
        bpm: float = 90,
        metronome: bool = True,
    ) -> None:
        super().__init__(config, engine, bot)
        self.beat_seconds = 60.0 / bpm
        self.bar_seconds = 4 * self.beat_seconds
        self.start = now + self.bar_seconds  # downbeat of bar 0; the bar before is the count-in
        self.metronome = metronome
        self.joker_held = False  # set by the screen from the Shift key
        self._next_bar = 0
        self._next_beat = -4  # the count-in's four beats are -4..-1
        self._clicks_off: list[tuple[float, int]] = []
        self._deadline: float | None = None  # waiting for a late chord until then
        self._released: tuple[Chord, float, bool] | None = None  # last chord let go: (chord, when, joker)
        self.phase = Phase.COUNT_IN
        self.bot.submit(self.round)

    # --- timing ---

    def bar_start(self, bar: int) -> float:
        return self.start + bar * self.bar_seconds

    def camera_at(self, now: float) -> float:
        """Roll position: the line in the middle of the roll is `now`."""
        return (now - self.start) / self.bar_seconds - 1

    @property
    def bar_label(self) -> str:
        if self.phase is Phase.COUNT_IN:
            return "count-in"
        return f"bar {self._next_bar} / {self.config.bars}"

    def count_in(self, now: float) -> int | None:
        """4, 3, 2, 1 during the count-in bar, None otherwise."""
        if now >= self.start:
            return None
        return max(1, min(4, math.ceil((self.start - now) / self.beat_seconds)))

    @property
    def preview_open(self) -> bool:
        return self.phase is Phase.BOT_BAR and not self.round.finished

    def _input_changed(self, before: Chord | None, now: float) -> None:
        if before is not None and self.input.chord is None:
            self._released = (before, now, self.joker_held)
        if self._deadline is not None:
            self._try_commit(now)  # a late press inside the grace window

    # --- the clock ---

    def update(self, now: float) -> None:
        self.player_voice.update(now)
        self.bot_voice.update(now)
        self._tick_metronome(now)
        while self.phase is not Phase.ROUND_OVER and self._next_bar < self.config.bars:
            if now < self.bar_start(self._next_bar):
                break
            self._downbeat(self._next_bar)
        if self._deadline is not None and now > self._deadline:
            self._player_misses(now)
        if self.phase is not Phase.ROUND_OVER and self._next_bar == self.config.bars:
            if now >= self.bar_start(self.config.bars) and self._deadline is None:
                self.player_voice.stop()
                self.bot_voice.stop()
                self._set_result()

    def _downbeat(self, bar: int) -> None:
        t = self.bar_start(bar)
        self._next_bar += 1
        if self._deadline is not None:
            self._player_misses(t)
        if bar % 2 == 0:
            self.phase = Phase.BOT_BAR
            self.player_voice.stop()
            move = self.bot.poll()
            if move is PENDING:
                self._miss(Side.BOT, "The bot ran out of time: it misses the bar", t)
            else:
                self._play_bot_move(move, t)
        else:
            self.phase = Phase.PLAYER_BAR
            self.bot_voice.stop()
            self._deadline = t + LATE_GRACE
            self._try_commit(t)

    def _held(self, now: float) -> tuple[Chord | None, bool]:
        """The chord to play now: the one held, or one let go only just before the downbeat."""
        if self.input.chord is not None:
            return self.input.chord, self.joker_held
        if self._released is not None:
            chord, when, joker = self._released
            downbeat = self.bar_start(self._next_bar - 1)
            if downbeat - EARLY_GRACE <= when <= now:
                return chord, joker
        return None, False

    def _try_commit(self, now: float) -> None:
        chord, joker = self._held(now)
        if chord is None:
            return
        error, joker = self._check(chord, joker)
        if error is not None:
            return  # maybe the player fixes it within the grace window
        self._deadline = None
        self._play_player(chord, joker, now)
        self.player_voice.stop()
        self.player_voice.play(chord, now)  # rings to the end of the bar, whatever the keys do
        self._after_player_bar()

    def _player_misses(self, now: float) -> None:
        self._deadline = None
        chord, joker = self._held(now)
        if chord is None:
            text = "Nothing held at the downbeat: you miss this bar"
        else:
            error, _ = self._check(chord, joker)
            text = f"{chord.name}: {error.value if error else 'not played'}, so you miss this bar"
        self._miss(Side.PLAYER, text, now)
        self._after_player_bar()

    def _after_player_bar(self) -> None:
        if not self.round.finished:
            self.bot.submit(self.round)

    def _tick_metronome(self, now: float) -> None:
        while self._clicks_off and self._clicks_off[0][0] <= now:
            _, note = self._clicks_off.pop(0)
            self.engine.note_off(METRONOME_CHANNEL, note)
        last_beat = 4 * self.config.bars
        while self._next_beat < last_beat and now >= self.start + self._next_beat * self.beat_seconds:
            beat = self._next_beat
            self._next_beat += 1
            if beat < 0 or self.metronome:
                note = CLICK_NOTES[0] if beat % 4 == 0 else CLICK_NOTES[1]
                self.engine.note_on(METRONOME_CHANNEL, note, 110)
                self._clicks_off.append((now + CLICK_LENGTH, note))

    def close(self) -> None:
        super().close()
        self.engine.all_notes_off(METRONOME_CHANNEL)
