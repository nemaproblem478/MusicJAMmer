# MusicJAMmer

A chord-jamming duel against an alpha-beta bot. The bot plays a chord, you
answer with one, and so on. Every bar adds tension to a shared pot; whoever
resolves it into their own key (a cadence) takes it.

## Rules

- You own a home key (C major by default); the bot owns the opposite key on the
  circle of fifths (F# major).
- A chord must share at least one note with the previous chord and move at most
  one step around the circle of fifths. No chord may repeat within 8 bars.
  Once per round you may play a joker: any chord, ignoring those rules.
- Each bar adds 1 to the pot (2 for a diminished chord).
- Cadence: if the bot's last chord contains your leading tone (B in C major),
  you may answer with your tonic chord (C) and take the pot. It works the other
  way round for the bot (its leading tone is F, i.e. E#). A cadence is always
  allowed.
- A pot nobody claims by the end of the round is lost. Most points wins.

## Modes

- **Untimed:** take as long as you like; Enter plays the chord you hold,
  Shift+Enter plays it as your joker.
- **Timed:** the roll moves at the chosen tempo after a one-bar count-in.
  Get your chord ready during the bot's bar and hold it as the line reaches
  your bar (with Shift for the joker). Nothing held, or an illegal chord, is a
  missed bar.

## Get the code

```sh
git clone https://github.com/nemaproblem478/MusicJAMmer.git
cd MusicJAMmer
```

Or on GitHub: **Code → Download ZIP**, then unzip it.

## macOS / Linux

You need Python 3.11 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m musicjammer                  # the game
```

Other things to run:

```sh
.venv/bin/python -m musicjammer.tools.piano      # sound check: play chords freely
.venv/bin/python -m pytest                       # tests
.venv/bin/python -m musicjammer.tools.selfplay   # bot-vs-bot rule statistics
```

### macOS app

```sh
sh packaging/build_mac.sh        # builds dist/MusicJAMmer.app and runs a self-test inside it
cp -R dist/MusicJAMmer.app /Applications/
```

The app bundles Python and every library, so it runs without the virtualenv.
It is signed ad hoc: it opens normally on the Mac that built it; on another Mac,
right-click it and choose Open the first time.

## Windows

> Not tested on Windows yet. Everything the game uses works there, but if
> something goes wrong, please open an issue.

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/).
   In the installer, tick **Add python.exe to PATH**.
2. Get the code (see above) and open **PowerShell** or **Command Prompt** in the
   `MusicJAMmer` folder (in Explorer: Shift + right-click the folder → *Open in Terminal*).
3. Install and run:

   ```bat
   py -m venv .venv
   .venv\Scripts\python -m pip install -e ".[dev]"
   .venv\Scripts\python -m musicjammer
   ```

   Next time, only the last line is needed.

Other things to run work the same way, e.g. `.venv\Scripts\python -m pytest`.

### Windows app (.exe)

```bat
packaging\build_windows.bat
```

This checks the game with a quick self-test, then builds
`dist\MusicJAMmer\MusicJAMmer.exe`. Keep the whole `dist\MusicJAMmer` folder
together (the .exe needs the files next to it); to launch it from the desktop or
the Start menu, right-click the .exe → *Show more options* → *Create shortcut*
and move the shortcut there.

The .exe isn't signed, so the first time Windows SmartScreen may warn about it:
click **More info → Run anyway**.

On Windows, settings live in `%USERPROFILE%\.musicjammer\settings.json` and
exported MIDI files in `%USERPROFILE%\Music\MusicJAMmer`.

## Sound and settings

Press `S` on the start screen for the sound page: wave, attack, decay, sustain,
release, a three-band EQ (low shelf 200 Hz, mid 1 kHz, high shelf 4 kHz,
±12 dB) and volume, for your synth and the bot's (Tab switches; `L` makes the
bot use your sound). Play chords while you tweak to hear the result.

Settings are saved in `~/.musicjammer/settings.json`. After a round, `E` saves
the jam as a MIDI file in `~/Music/MusicJAMmer` (see above for Windows paths).

## Controls

| Row | Keys | Meaning |
|---|---|---|
| Root (hold) | `A W S E D F T G Y H U J` | C C# D D# E F F# G G# A A# B |
| Chord type (latches) | `Z X C` | maj, min, dim |
| Extension (toggles) | `6 7 8 9` | 6th, 7th, maj7, add9 (none = root an octave up) |
| Play the chord | `Enter` | `Shift+Enter` plays it as your joker |

Keys are read by physical position, so any keyboard layout works.
