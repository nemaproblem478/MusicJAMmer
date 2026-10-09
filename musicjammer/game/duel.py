"""Cadence duel: both sides build up tension; whoever resolves it into their own key takes it.

Each side has a home key (the bot's defaults to the opposite side of the circle
of fifths). Every bar adds its chord's tension to a shared pot. A cadence
happens when the opponent has just played one of your dominants (V or vii° of
your key) and you answer with your tonic: you take the whole pot. A cadence is
always legal, even when the connection rules or the repeat ban would forbid it.
(`cadence_rule` can widen "dominant" to any chord holding your leading tone.)

Nobody plays the other side's dominant on purpose, so cadences come from
traps: positions where every legal move hands the opponent a cadence.

At the end of the round an unclaimed pot goes to the side whose tonic is
closer (on the circle of fifths) to the last chord. The tonic of the player's
key sounds "silently" before the first bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..theory import DIM, MAJ, Chord, Key, MoveError, RuleSet, all_cores, check_move, distance
from .common import IllegalMove, Side

# Which opponent chords set up your cadence:
#   "dominant"      V or vii° of your key
#   "leading_tone"  any chord containing your leading tone (the note a semitone below your tonic)
CADENCE_RULES = ("dominant", "leading_tone")
# What happens to a pot nobody claimed by the end of the round:
#   "closer"  it goes to the side whose tonic is closer to the last chord
#   "burn"    it is lost
LEFTOVER_RULES = ("closer", "burn")


def dominants(key: Key) -> frozenset[Chord]:
    """V (always major, also in minor keys) and vii° of the key."""
    return frozenset({Chord(key.tonic + 7, MAJ), Chord(key.tonic + 11, DIM)})


def cadence_setups(key: Key, rule: str = "dominant") -> frozenset[Chord]:
    """Core chords that, played by the opponent, let you resolve into the key's tonic."""
    if rule == "dominant":
        return dominants(key)
    leading_tone = (key.tonic + 11) % 12
    return frozenset(c for c in all_cores() if leading_tone in c.pitch_classes)


def tension(chord: Chord) -> int:
    return 1 + chord.type.tension


@dataclass(frozen=True)
class DuelConfig:
    key: Key  # the player's home key
    bot_key: Key | None = None  # None = the key opposite the player's on the circle of fifths
    bars: int = 16
    rules: RuleSet = field(default_factory=RuleSet)
    jokers: int = 1  # per side, per round
    cadence_rule: str = "leading_tone"
    leftover: str = "burn"

    def __post_init__(self) -> None:
        if self.bars <= 0 or self.bars % 2:
            raise ValueError("a round needs a positive, even number of bars")
        if self.cadence_rule not in CADENCE_RULES or self.leftover not in LEFTOVER_RULES:
            raise ValueError("unknown cadence or leftover rule")
        if self.bot_key is None:
            object.__setattr__(self, "bot_key", Key(self.key.tonic + 6, self.key.mode))

    def home(self, side: Side) -> Key:
        return self.key if side is Side.PLAYER else self.bot_key


@dataclass(frozen=True)
class DuelBar:
    side: Side
    chord: Chord | None  # None = missed
    joker: bool
    cadence: bool
    pot_after: int
    won: int  # points taken this bar


class DuelRound:
    def __init__(self, config: DuelConfig) -> None:
        self.config = config
        self.bars: list[DuelBar] = []
        self.chords: list[Chord] = []
        self.jokers_left = {side: config.jokers for side in Side}
        self.points = {side: 0 for side in Side}
        self.pot = 0
        self.leftover: tuple[Side | None, int] | None = None  # who got the unclaimed pot at the end

    @property
    def side_to_move(self) -> Side:
        return Side.BOT if len(self.bars) % 2 == 0 else Side.PLAYER

    @property
    def bars_left(self) -> int:
        return self.config.bars - len(self.bars)

    @property
    def finished(self) -> bool:
        return self.bars_left == 0

    @property
    def previous_chord(self) -> Chord:
        return self.chords[-1] if self.chords else self.config.key.tonic_chord

    def is_cadence(self, chord: Chord) -> bool:
        """Whether playing `chord` now resolves the opponent's last chord into our home tonic."""
        if not self.bars or self.bars[-1].chord is None:
            return False
        home = self.config.home(self.side_to_move)
        setups = cadence_setups(home, self.config.cadence_rule)
        return self.bars[-1].chord.core in setups and chord.core == home.tonic_chord

    def check(self, chord: Chord, joker: bool = False) -> MoveError | None:
        if self.is_cadence(chord):
            return None
        if joker and self.jokers_left[self.side_to_move] == 0:
            return MoveError.NO_JOKERS
        return check_move(chord, self.chords, self.config.rules, self.previous_chord, joker)

    def play(self, chord: Chord, joker: bool = False) -> DuelBar:
        if self.finished:
            raise RuntimeError("the round is over")
        cadence = self.is_cadence(chord)
        if cadence:
            joker = False  # a cadence never needs one
        reason = self.check(chord, joker)
        if reason is not None:
            raise IllegalMove(chord, reason)
        side = self.side_to_move
        if joker:
            self.jokers_left[side] -= 1
        self.chords.append(chord)
        won = 0
        if cadence:
            won, self.pot = self.pot, 0
            self.points[side] += won
        else:
            self.pot += tension(chord)
        return self._add(DuelBar(side, chord, joker, cadence, self.pot, won))

    def miss(self) -> DuelBar:
        if self.finished:
            raise RuntimeError("the round is over")
        self.pot += 1
        return self._add(DuelBar(self.side_to_move, None, False, False, self.pot, 0))

    def _add(self, bar: DuelBar) -> DuelBar:
        self.bars.append(bar)
        if self.finished:
            self._settle()
        return bar

    def _settle(self) -> None:
        owner = closer_side(self.previous_chord, self.config) if self.config.leftover == "closer" else None
        if owner is not None:
            self.points[owner] += self.pot
        self.leftover, self.pot = (owner, self.pot), 0

    @property
    def score(self) -> int:
        """Player's points minus the bot's: positive is the player's side."""
        return self.points[Side.PLAYER] - self.points[Side.BOT]

    @property
    def winner(self) -> Side | None:
        if not self.finished or self.score == 0:
            return None
        return Side.PLAYER if self.score > 0 else Side.BOT


def closer_side(chord: Chord, config: DuelConfig) -> Side | None:
    """The side whose home tonic is closer to the chord, or None on a tie."""
    to_player = distance(chord, config.key)
    to_bot = distance(chord, config.bot_key)
    if to_player == to_bot:
        return None
    return Side.PLAYER if to_player < to_bot else Side.BOT
