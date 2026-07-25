# DJ Visualizer — Stage 1: Rekordbox + Live Audio Pipeline

Stage 1 of the technique-aware DJ visualizer. This stage builds the two
independent, reliable data sources everything else depends on:

1. **Rekordbox library adapter** — reads your local collection, per-track
   waveform + beatgrid + cue data (from the ANLZ analysis files Rekordbox
   already computes), via `pyrekordbox`.
2. **Live audio pipeline** — captures the system's audio output (loopback)
   and runs real-time onset/tempo detection with `aubio`, independent of any
   DJ software's internals. This is the layer that actually works
   regardless of what's playing.

A FastAPI app ties them together and streams events over a WebSocket
(`/ws/events`) so a future visual frontend can just listen.

**What's intentionally NOT solved yet:** a guaranteed "here's the exact
track playing right now" signal from Rekordbox's live database. Rekordbox's
schema for history/now-playing isn't publicly documented and has changed
across versions — see `docs/rekordbox_schema_notes.md` for how to verify it
against your own install rather than trusting a hardcoded query. This is a
deliberate choice: better to ship a working audio-only track-change
detector now and wire in the DB confirmation once verified, than to ship a
confident-looking query that silently breaks on your version.

## Project layout

```
dj-visualizer/
  app/
    main.py                FastAPI app, background tasks, WebSocket endpoint
    config.py               Settings (env vars)
    events.py                Pydantic event models
    bus.py                    Tiny async pub/sub event bus
    rekordbox/
      library.py               Collection reader + schema explorer
      analysis.py               ANLZ waveform/beatgrid/cue parsing
      now_playing.py             Best-effort live "now playing" poller (see caveat above)
    audio/
      capture.py                 Cross-platform loopback/mic capture (soundcard)
      features.py                  Real-time onset/tempo (aubio, with numpy fallback)
      fallback_onset.py             Pure-numpy spectral-flux onset detector
    ws/
      manager.py                     WebSocket connection manager
  scripts/
    list_audio_devices.py            Find your loopback device name
    rekordbox_smoke_test.py           Verify pyrekordbox can read your library
    explore_rekordbox_schema.py        Dump table/column names for now_playing.py
  requirements.txt
```

## Setup

### 1. Python environment

```bash
cd dj-visualizer
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`aubio` occasionally fails to build from source on Windows if you don't have
build tools installed. If `pip install aubio` fails:
- Try `pip install aubio --only-binary :all:` first (prebuilt wheel).
- If that fails, install the "Desktop development with C++" workload from
  the Visual Studio Build Tools installer, then retry.
- If you still can't get it working, that's fine — `app/audio/features.py`
  automatically falls back to a pure-numpy onset detector
  (`fallback_onset.py`) with a logged warning. It's less accurate but keeps
  the pipeline running so you're not blocked.

### 2. Audio loopback setup (this is the fiddly part, platform-specific)

Neither OS lets you capture "what's currently playing out of the speakers"
without a small setup step:

**macOS:** Install [BlackHole](https://existential.audio/blackhole/) (free,
2ch is enough). Then, in **Audio MIDI Setup**, create a **Multi-Output
Device** combining your normal output (headphones/speakers) + BlackHole 2ch,
and set that Multi-Output Device as your system output. This way you still
hear your mix, *and* BlackHole gets a copy of the signal that this app can
read as a normal input device.

**Windows:** No extra driver needed. This project uses the `soundcard`
library, which supports native WASAPI loopback recording — it can record
directly from your default output device without any virtual cable. Just
run `scripts/list_audio_devices.py` and pick your speaker/output device;
the capture code requests it in loopback mode automatically.

**Linux:** Use PulseAudio/PipeWire's monitor source (e.g.
`Monitor of Built-in Audio Analog Stereo`) — it shows up as a normal input
device, same idea as BlackHole.

Run this to find the right device name for your `.env`:

```bash
python scripts/list_audio_devices.py
```

Then set it:

```bash
# .env
AUDIO_DEVICE_NAME=BlackHole 2ch          # macOS example
# AUDIO_DEVICE_NAME=Speakers (Realtek)   # Windows example — loopback is automatic
```

### 3. Point at your Rekordbox library

`pyrekordbox` auto-detects your Rekordbox install location on both
platforms. Run the smoke test:

```bash
python scripts/rekordbox_smoke_test.py
```

This should print your collection size and a sample track's waveform/beatgrid
info. If it fails on the database step (SQLCipher key issues — this happens
after Rekordbox updates sometimes), it will fall back to XML-only mode if
you have an exported XML database, and tell you what to do.

### 4. Verify the now-playing schema before relying on it

```bash
python scripts/explore_rekordbox_schema.py
```

Play a track in Rekordbox, run the script, and look for a table whose most
recently-updated row corresponds to what's playing. Update the table/column
names in `app/rekordbox/now_playing.py` (they're pulled into constants at
the top of the file) once you've confirmed them on your version.

### 5. Run it

```bash
uvicorn app.main:app --reload
```

Then connect a WebSocket client to `ws://localhost:8000/ws/events` — you
should see `audio.onset` / `audio.tempo` events streaming immediately once
audio is flowing through your loopback device, and `rekordbox.library.ready`
on startup. `rekordbox.now_playing` events will appear once you've verified
and wired up step 4.

## Next stages (not built yet)

- **Stage 2:** genre-conditioned technique classifier consuming this event
  stream (bass swap / filter sweep / echo-out / loop roll / double drop
  detection — see the research brief for feature definitions).
- **Stage 3:** WebGL/Hydra-based visual renderer subscribing to classified
  technique events.
- **Serato adapter** (history-file tailing + GEOB ID3 tag parsing) as a
  second input source, once Rekordbox path is solid.
