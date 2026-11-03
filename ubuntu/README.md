# Cicada on Ubuntu 26.04 (preview)

Python/PySide6 implementation alongside the existing Swift macOS app. First milestone:
playback audio → selectable local/cloud ASR → captions → translation → periodic notes → saved history/Markdown export.

## Development setup

Requires PipeWire with `pipewire-pulse` or PulseAudio. Discovery uses `pactl` and capture uses `libpulse`.

```bash
sudo apt install python3-venv pulseaudio-utils libegl1 libgl1
cd ubuntu
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[local]'
cicada
```

Cloud-only users can install `-e .` without the local extra. Start with local model `small`, device `auto` (CUDA with CPU fallback), language `auto` or an ISO language such as `en`/`zh`. The local model is downloaded on first use; an existing model directory can be supplied instead. NVIDIA execution requires the CUDA/cuDNN versions supported by faster-whisper/CTranslate2, independently of your PyTorch installation.

Select the monitor for your playback output. All sound on that output is captured, including notifications. Capture stops if the selected monitor disappears or the recording stream moves. Select a monitor again to resume. Captions arrive after a pause or at most eight seconds of continuous audio, plus provider latency. This is segmented transcription, not token-by-token streaming.

Cloud mode sends WAV segments to the configured OpenAI-compatible `/audio/transcriptions` endpoint. Set its base URL (including `/v1`), transcription model and ASR key. Provider-specific streaming protocols are not supported. There is no automatic fallback from local to cloud.

Translation and notes use a separately configured OpenAI-compatible `/chat/completions` endpoint, model and text key. Leaving the text key empty gives transcription/history only. Notes refresh about every 45 seconds of processing and at a normal stop. Model/provider availability must be configured for your account.

Press Stop to finish queued speech and save notes. Closing during capture requests a stop; close again once processing finishes. Network calls have a 45-second timeout; draining queued speech can take longer. Errors retain already recognized lines. The bounded capture queue stops the session if providers cannot keep up.

## Where to change code

| Concern | Location | Boundary |
|---|---|---|
| Session/line fields and export | `core.py` | Plain Python values; no UI/OS/model imports |
| Session lifecycle and failure handling | `workflow.py` | Injected capture, recognizer, text service and store |
| Ubuntu audio and segmentation | `pipewire.py`, `pulse.py` | Monitor discovery, segmentation and fixed-source capture |
| Local/cloud ASR and text providers | `providers.py` | Same `transcribe(Audio)` contract; network isolated here |
| Linux persistence | `storage.py` | Atomic snapshots; XDG paths |
| Widgets and application wiring | `ui.py` | Chooses adapters; blocking work lives in a worker |

To add an ASR provider, implement `transcribe(Audio)` and select it in the composition root. To replace audio capture, implement `chunks(stop)`. Neither change requires modifying session/export rules. macOS remains Swift; the two implementations do not share executable business logic.

Session JSON preserves macOS transcript field names (`id`, `t`, `speaker`, `src`, `dst`, `srcLang`, `dstLang`) and ISO dates. Ubuntu notes currently use an additional `notesText` field rather than the macOS structured notes object; full notes interchange is not claimed. No audio recordings are stored. Sessions and settings (including keys) use mode 0600 beneath `$XDG_DATA_HOME/cicada` (default `~/.local/share/cicada`). Do not export settings or commit keys.

## Verification

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q cicada_linux
```

The tests cover audio conservation, quiet input, pause boundaries, disconnect tails, malformed history, cloud request formatting and failure persistence. The live capture probe starts an isolated audio server with two temporary sinks and checks that capture ends when the selected monitor disappears. From the repository root, run `dbus-run-session -- bash ubuntu/tests/run_live_capture.sh pulseaudio` or use `pipewire` with PipeWire, PipeWire-pulse and WirePlumber installed.

Manual Ubuntu acceptance: play known speech, select its monitor, test local CPU then CUDA, test a configured cloud endpoint, confirm bilingual captions and notes, Stop, restart, inspect history and export Markdown. Test a disconnected output and provider failure. Check on the actual Wayland desktop and multiple displays.

## Current limitations

The Ubuntu 26.04 desktop, GPU inference and authenticated provider calls still require acceptance testing. Segmentation prefers nearby pauses and retains quiet audio. Continuous speech can still split at the eight-second limit. The separate captions window is an ordinary Qt tool window: positioning/always-on-top follows the compositor; screen-share exclusion and macOS overlay behaviour are not implemented. No global hotkeys, virtual microphone, speech synthesis, speaker identification, desktop installer or automatic updates in this milestone.
