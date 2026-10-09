"""Saving a finished jam as a standard MIDI file, to open in any DAW.

One track per side (the player on channel 1, the bot on channel 2), one chord
per 4/4 bar, voiced and strummed the way the game played it. Missed bars are
rests. Untimed rounds are written at the tempo from the settings.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

import mido

from .audio import BOT_CHANNEL, PLAYER_CHANNEL
from .game import DuelConfig, Side
from .session import Block

TICKS_PER_BEAT = 480
STRUM_SECONDS = 0.06
BASE_NOTE = 48
VELOCITY = 96
PROGRAMS = {Side.PLAYER: 4, Side.BOT: 4}  # General MIDI Electric Piano 1


def jam_to_midi(blocks: Sequence[Block], config: DuelConfig, bpm: float) -> mido.MidiFile:
    midi = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
    bar_ticks = 4 * TICKS_PER_BEAT
    strum_ticks = round(STRUM_SECONDS * bpm / 60 * TICKS_PER_BEAT)

    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name=f"MusicJAMmer: {config.key} vs {config.bot_key}"))
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
    conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4))
    midi.tracks.append(conductor)

    for side, channel, name in ((Side.PLAYER, PLAYER_CHANNEL, "You"), (Side.BOT, BOT_CHANNEL, "Bot")):
        events: list[tuple[int, int, mido.Message]] = []  # (tick, order, message); note-offs sort first
        for bar, block in enumerate(blocks):
            if block.side is not side or block.chord is None:
                continue
            start, end = bar * bar_ticks, (bar + 1) * bar_ticks
            for k, note in enumerate(block.chord.voicing(BASE_NOTE)):
                on = start + k * strum_ticks
                events.append((on, 1, mido.Message("note_on", channel=channel, note=note, velocity=VELOCITY)))
                events.append((end, 0, mido.Message("note_off", channel=channel, note=note, velocity=0)))
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=name))
        track.append(mido.Message("program_change", channel=channel, program=PROGRAMS[side]))
        now = 0
        for tick, _, message in sorted(events, key=lambda e: (e[0], e[1])):
            track.append(message.copy(time=tick - now))
            now = tick
        midi.tracks.append(track)
    return midi


def default_export_dir() -> Path:
    return Path.home() / "Music" / "MusicJAMmer"


def save_jam(blocks: Sequence[Block], config: DuelConfig, bpm: float, directory: Path | None = None) -> Path:
    directory = directory or default_export_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H.%M.%S")
    path = directory / f"jam {stamp}.mid"
    jam_to_midi(blocks, config, bpm).save(path)
    return path
