"""Game and sound settings, kept between runs in a small JSON file.

The file lives at ~/.musicjammer/settings.json (MUSICJAMMER_SETTINGS overrides
the path). Anything missing, unknown or out of range falls back to the
defaults, so an old or hand-edited file never stops the game from starting.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from .ai import DIFFICULTIES
from .audio import BOT_CHANNEL, PLAYER_CHANNEL, NoteEngine
from .game import ROUND_LENGTHS, DuelConfig
from .theory import MODES, Key

VERSION = 1
BPM_RANGE = (50, 180)


@dataclass(frozen=True)
class GameSettings:
    tonic: int = 0
    mode: str = "major"
    difficulty: str = "medium"
    bars: int = 16
    preview_volume: float = 0.6  # untimed: your chords while you pick one
    bot_volume: float = 0.8  # untimed: the bot's chord while you pick yours
    timed: bool = False
    bpm: int = 90
    metronome: bool = True

    def config(self) -> DuelConfig:
        return DuelConfig(Key(self.tonic, MODES[self.mode]), bars=self.bars)

    def sanitized(self) -> GameSettings:
        """The same settings with anything invalid replaced by its default."""
        default = GameSettings()
        valid = {
            "tonic": isinstance(self.tonic, int) and 0 <= self.tonic < 12,
            "mode": self.mode in MODES,
            "difficulty": self.difficulty in DIFFICULTIES,
            "bars": self.bars in ROUND_LENGTHS,
            "preview_volume": isinstance(self.preview_volume, (int, float)) and 0 <= self.preview_volume <= 1,
            "bot_volume": isinstance(self.bot_volume, (int, float)) and 0 <= self.bot_volume <= 1,
            "timed": isinstance(self.timed, bool),
            "bpm": isinstance(self.bpm, int) and BPM_RANGE[0] <= self.bpm <= BPM_RANGE[1],
            "metronome": isinstance(self.metronome, bool),
        }
        return replace(self, **{name: getattr(default, name) for name, ok in valid.items() if not ok})


def settings_path() -> Path:
    override = os.environ.get("MUSICJAMMER_SETTINGS")
    return Path(override) if override else Path.home() / ".musicjammer" / "settings.json"


class SettingsStore:
    """The game settings plus the synth parameters of the player's and the bot's channels."""

    def __init__(self, engine: NoteEngine, path: Path | None = None) -> None:
        self.engine = engine
        self.path = path or settings_path()
        self.game = GameSettings()
        self.bot_linked = True  # the bot plays with the player's sound

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        game = data.get("game", {})
        if isinstance(game, dict):
            known = {f.name for f in fields(GameSettings)}
            self.game = GameSettings(**{k: v for k, v in game.items() if k in known}).sanitized()
        synth = data.get("synth", {})
        if isinstance(synth, dict):
            self._load_channel(PLAYER_CHANNEL, synth.get("player"))
            self.bot_linked = synth.get("bot_linked", True) is not False
            self._load_channel(BOT_CHANNEL, synth.get("bot"))
        self.sync_bot()

    def _load_channel(self, channel: int, values) -> None:
        if not isinstance(values, dict):
            return
        known = {p.id for p in self.engine.params()}
        for param_id, value in values.items():
            if param_id in known:
                try:
                    self.engine.set_param(channel, param_id, value)
                except (TypeError, ValueError):
                    pass  # keep the default

    def sync_bot(self) -> None:
        """While linked, the bot's channel copies the player's sound."""
        if self.bot_linked:
            self.engine.copy_params(PLAYER_CHANNEL, BOT_CHANNEL)

    def save(self) -> None:
        params = [p.id for p in self.engine.params()]
        data = {
            "version": VERSION,
            "game": asdict(self.game),
            "synth": {
                "player": {p: self.engine.get_param(PLAYER_CHANNEL, p) for p in params},
                "bot": {p: self.engine.get_param(BOT_CHANNEL, p) for p in params},
                "bot_linked": self.bot_linked,
            },
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(self.path)  # never leave a half-written file behind
        except OSError:
            pass  # settings are a convenience; the game goes on without them
