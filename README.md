# Jarvis — private local Windows assistant

Jarvis Phase 5 is a working text, voice, wake-word, tray, vision, media, local-music, and persistent-memory Windows assistant. AI processing stays local through Ollama `gemma64`; no cloud AI fallback or telemetry exists.

## Current phase

Implemented now:

- strict YAML configuration;
- Ollama health/model checks, async streaming chat, retries, cancellation, tools, and image-capable message transport;
- central Slovak/English safety prompt and 64K-aware bounded context with local compaction;
- typed Pydantic tool schemas/results and permission enforcement;
- configured plus automatic installed-application and Steam-game discovery/open/focus/listing;
- bounded file/folder search, open, listing, metadata, recent files, and direct text extraction;
- active-window and system information tools;
- safe window management, exact Core Audio volume, Bluetooth-device enumeration, and desktop locking with confirmation;
- public web search/page reading, named website-section navigation, YouTube search/autoplay, browser opening, and validated input tools;
- on-demand microphone capture with adaptive VAD and silence stop;
- offline-by-default Slovak/English faster-whisper transcription;
- queued Piper speech with voice selection and cancellation;
- native global push-to-talk and stop-speaking hotkeys;
- local `Hey Jarvis` detection through openWakeWord ONNX with no audio retention;
- Windows system tray with live sleeping/listening/thinking/speaking/error states and local notifications;
- shared main-thread tkinter settings, status, and confirmation windows;
- foreground tray mode and hidden `pythonw` background startup;
- one-shot full-screen and active-window capture using mss and trusted Win32 bounds;
- local `gemma64` screen description, visible-content summary, error reading, and UI-element location;
- image resize/encoding in memory with validated virtual-desktop coordinates;
- Windows GSMTC media controls with a predefined media-key fallback and Core Audio volume;
- bounded local music search and validated audio-file playback;
- SQLite short-term history, explicitly approved facts/preferences, and application/folder aliases;
- optional official Spotify Web API playback control, disabled by default and token-only through an environment variable;
- PyInstaller one-folder packaging script;
- rotating logs and pytest coverage.

Wake-word mode evaluates short audio frames locally without saving them. Screenshots are captured only on demand. Permanent memory is written only for an explicit remember/preference/alias request and rejects credential-like data.

## Requirements

- Windows 11, preferably 64-bit;
- Python 3.13.x from [python.org](https://www.python.org/downloads/windows/); the `py` launcher is needed only when creating a missing `.venv`;
- Ollama running locally;
- the existing custom `gemma64` model;
- a locally cached faster-whisper model (default `medium`);
- Piper executable plus at least one local `.onnx` voice;
- AMD Radeon RX 7800 XT (16 GB VRAM) for the target deployment.

Phase 1–5 dependencies in `requirements.txt` resolve to Windows CPython 3.13-compatible wheels. Phase 5 uses `winrt-runtime` 3.x/Windows Media projections and pycaw. Optional PDF/DOCX readers and PyInstaller are in the `documents` and `packaging` extras.

## Install

Open PowerShell in this directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

The script verifies Windows and Python 3.13, creates `.venv`, installs Phase 1–5 dependencies, creates `config.yaml`, lists microphones, checks local Ollama/gemma64/Whisper/Piper/openWakeWord/vision/media state, and runs tests. It does not install Ollama or silently download voice, Whisper, LLM, or wake-word weights.

Manual equivalent:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
python -m pytest
python main.py --check
python main.py --text
```

The faster-whisper model is deliberately not downloaded during installation. After reviewing its disk size, download `medium` explicitly:

```powershell
.\.venv\Scripts\python.exe -m audio.speech_to_text --download-model medium
```

This setup command downloads model weights only; microphone audio is never uploaded. For a fully offline transfer, copy a converted faster-whisper model directory onto the computer and set `speech_to_text.model` to that directory.

The repository can contain the three required ONNX wake-word assets under `assets\wake_words`. If they are missing, download only those official openWakeWord files explicitly:

```powershell
.\.venv\Scripts\python.exe -m audio.wake_word --download-model --config config.yaml
.\.venv\Scripts\python.exe -m audio.wake_word --check-model --config config.yaml
```

Jarvis never downloads wake-word models during normal startup.

## Ollama and gemma64

Start Ollama, then verify the only model Jarvis will use:

```powershell
ollama list
ollama show gemma64
ollama run gemma64
```

`config.yaml` must retain:

```yaml
ollama:
  base_url: http://localhost:11434
  model: gemma64
  context_size: 65536
  max_output_tokens: 768
```

`ollama show gemma64` should show the custom Modelfile parameters/context metadata. If it does not reflect 65,536 tokens, rebuild the custom model outside Jarvis; Jarvis never pulls or replaces it. Each chat request also sends `num_ctx: 65536`.

If Ollama is unavailable, start its Windows application/service. If `gemma64` is missing, Jarvis exits and suggests `ollama list`; it never substitutes another model.

## AMD Radeon RX 7800 XT

Keep Windows 11 and AMD Adrenalin drivers current. Start `ollama run gemma64`, submit a prompt, then inspect `ollama ps`: it reports whether the model is using GPU, CPU, or a split. A 64K context consumes substantial VRAM; close GPU-heavy apps and reduce concurrent Ollama loads. Jarvis makes one model request stream at a time and sets `keep_alive: 30m`.

If generation runs on CPU or fails:

1. update AMD Adrenalin and Ollama;
2. restart Windows and Ollama;
3. verify `ollama run gemma64` independently;
4. inspect Ollama logs and `ollama ps`;
5. confirm no environment override forces an unsupported runner.

Do not install a second model as an automatic workaround.

## Configuration

Copy and edit `config.example.yaml` as `config.yaml`.

### Searchable folders

Defaults are the current user's Desktop, Documents, Downloads, and Music. Add only directories Jarvis may inspect:

```yaml
files:
  searchable_directories:
    - Desktop
    - Documents
    - Downloads
    - Music
    - D:\Projects
```

Resolved paths must remain inside these roots. Credential/key extensions and known credential/browser/system folders remain blocked. Symlink resolution cannot escape an allowed root.

### Applications

Jarvis accepts an application or game name, never a model-generated executable path. With discovery enabled it searches trusted local Start Menu `.lnk`/`.url` shortcuts, installed Steam manifests, Windows App Paths, and running executable paths. The allowlist remains useful for aliases and exact overrides:

```yaml
applications:
  allow_discovered_applications: true
  allowlist:
    - name: Visual Studio Code
      executable_path: C:\Users\YOUR_NAME\AppData\Local\Programs\Microsoft VS Code\Code.exe
      aliases: [VS Code, Code]
```

Set `allow_discovered_applications: false` to restore strict allowlist-only mode. Ambiguous or unresolved names fail safely instead of executing a guessed path.

### Public web and YouTube

Public browsing is opt-in through configuration and enabled in the supplied local config:

```yaml
browser:
  preferred_browser: Chrome
  search_url: https://www.google.com/search?q={query}
  web_access_enabled: true
  request_timeout_seconds: 15
  max_page_characters: 12000
  max_search_results: 5
```

`search_public_web` uses the public DuckDuckGo HTML search surface and `read_public_webpage` extracts bounded visible text without JavaScript, cookies, browser profiles, or authentication. `open_web_section` resolves a named service and section, then opens the best public result in the default browser; for example, "Vyhľadaj My Forza a choď na časť stránky, kde sú screenshoty." opens the official My Forza gallery entry. The browser may use its existing signed-in session, but Jarvis never reads its cookies or private profile. Local/private/reserved network addresses and credential-bearing URLs are blocked. `play_youtube` searches the public YouTube results page, opens the first video with autoplay, and then uses normal Windows media controls for pause/resume/stop. These network requests disclose the explicit search query or requested public URL to the corresponding website; they never involve a cloud AI provider.

Common one-step commands are routed deterministically without waiting for `gemma64`. For model-assisted requests, Jarvis sends only the relevant tool schemas instead of the complete registry and limits the default response budget with `ollama.max_output_tokens`; this reduces prompt processing and overly long spoken answers.

### Microphone and transcription

List PortAudio input devices:

```powershell
.\.venv\Scripts\python.exe -m audio.recorder
```

Set either a device index or an exact device-name substring. Windows may expose one physical microphone through several host APIs.

```yaml
audio:
  microphone_device: 1
  sample_rate: 16000
  block_duration_ms: 30
  silence_timeout_seconds: 1.2
  maximum_recording_seconds: 30

speech_to_text:
  model: medium
  language: auto
  device: auto
  compute_type: auto
  allow_model_download: false
```

On the target Radeon system, `auto` intentionally selects CPU `int8` for faster-whisper because its CTranslate2 GPU backend targets CUDA, not AMD DirectML. Ollama can still use the Radeon GPU for `gemma64`.

### Piper voices

Configure a local Piper-compatible executable and downloaded voice files. `voice_model_path` is the primary/Slovak voice. Jarvis selects the voice from the final answer text, with transcription language only as fallback, so a mistaken input-language detection no longer makes English Piper read Slovak.

Spoken output is normalized separately from the complete text response: Markdown, URLs, code blocks, and raw Windows paths are not read verbatim, and speech defaults to three sentences/420 characters. A local Piper/Whisper comparison selected `speaking_rate: 0.9` for clearer Slovak. `wake_word.resume_delay_seconds: 1.0` suppresses post-speech echo, while wake-word barge-in remains active during speech. All values are configurable under `text_to_speech` and `wake_word`.

```yaml
text_to_speech:
  provider: piper
  executable_path: C:\Tools\piper\piper.exe
  voice_model_path: C:\Tools\piper\voices\sk_SK-voice.onnx
  english_voice_model_path: C:\Tools\piper\voices\en_US-voice.onnx
  speaking_rate: 0.9
  output_device: null
```

Keep each voice's adjacent `.onnx.json` file. Test speech locally:

```powershell
.\.venv\Scripts\python.exe -m audio.text_to_speech --text "Ahoj, som Jarvis." --language sk
.\.venv\Scripts\python.exe -m audio.text_to_speech --text "Hello, I am Jarvis." --language en
```

### Wake word and tray

The bundled official model recognizes **Hey Jarvis**. `wake_word.phrase` is the user-facing label; changing it does not retrain the model. A different phrase requires an explicitly configured compatible openWakeWord ONNX model plus its local feature assets.

```yaml
wake_word:
  enabled: true
  phrase: Jarvis
  sensitivity: 0.5
  model_path: assets/wake_words/hey_jarvis_v0.1.onnx
  cooldown_seconds: 2.0
```

Lower the threshold to reduce missed activations; raise it to reduce false activations. Higher values can miss quiet speech. The Settings tray action edits Ollama, microphone, Whisper, Piper, wake word, hotkeys, folders, applications, screenshot limits, permissions, logging, and UI options. Saved changes take effect after restart.

### Screenshot understanding

Vision capture is always one-shot. For “this”, “this window”, or “what is open”, Jarvis prefers the active window. Full-screen requests capture the complete virtual desktop, including multiple monitors, then resize it within configured limits:

```yaml
vision:
  max_width: 1600
  max_height: 900
  jpeg_quality: 85
  save_debug_screenshots: false
```

Pixels are held in memory, sent only to the configured loopback Ollama server, and released after analysis. No image or base64 payload enters conversation history or logs. When `save_debug_screenshots` is explicitly enabled, resized JPEGs are retained under `debug_screenshots`; the Settings window exposes this switch.

`locate_visible_ui_element` returns a model-estimated normalized box only after Pydantic validation, then maps it to validated virtual-desktop coordinates. It never clicks the element. Visible websites, files, dialogs, and screenshot text remain untrusted and cannot override Jarvis instructions.

## Run and test

Configuration/Ollama check:

```powershell
.\run.ps1 -Check
```

Text mode:

```powershell
.\run.ps1
```

Push-to-talk voice mode:

```powershell
.\run.ps1 -Voice
```

Tray mode with a diagnostic terminal:

```powershell
.\run.ps1 -Tray
```

Normal background mode without an extra terminal window:

```powershell
.\run.ps1 -Background
```

Use the tray menu to start/stop wake listening, push to talk, mute Jarvis, stop speech, open settings/status/logs, clear conversation history, restart, or quit.

Say `Hey Jarvis` or press `Ctrl+Alt+Space` to capture one request. Recording stops after silence. Press `Ctrl+Alt+X` to stop listening, transcription, model generation, or speech. Activated phrases `stop`, `prestaň`, and `ticho` also suppress further speech.

Vision examples:

```text
Jarvis, čo vidíš na obrazovke?
Jarvis, zosumarizuj toto okno.
Jarvis, čo znamená táto chyba?
Jarvis, nájdi tlačidlo Settings.
Jarvis, opíš mi túto aplikáciu.
```

Try:

```text
Which applications are running?
Open Notepad.
Focus Visual Studio Code.
Open Puck.
Koľko je teraz hodín?
Vyhľadaj na webe novinky o AMD Radeon.
Vyhľadaj herný volant.
Vyhľadaj My Forza a choď na časť stránky, kde sú screenshoty.
Pusti na YouTube Daft Punk Around the World.
Pozastav video.
Pokračuj vo videu.
Stlm zvuk.
Zapni zvuk.
Find files named report.
Find folders matching projects.
What is the active window?
How much memory is in use?
Summarize C:\Users\YOUR_NAME\Documents\notes.md.
Pause music.
Čo práve hrá?
Nájdi lokálnu hudbu s názvom favorite.
Čo si o mne pamätáš?
Zapamätaj si, že preferujem stručné odpovede.
```

Use `/clear` to clear active conversation history and `/quit` to exit text mode. Medium-risk actions such as opening a specific file print a local action notice. No high-risk tools are registered.

Run tests directly:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Music, Spotify, and memory

Local media commands use Windows Global System Media Transport Controls. When an application exposes no session, only the fixed play/pause/next/previous/stop media keys are available; Jarvis reports that playback could not be confirmed. `set_media_volume` uses Windows Core Audio.

Local music search accepts MP3, FLAC, WAV, M4A, AAC, OGG, OPUS, and WMA only under `music.directories`. It never searches the whole drive by default.

Spotify is off by default. To opt in, obtain a user OAuth token with `user-read-playback-state` and `user-modify-playback-state`, keep it out of YAML, then start Jarvis from the same PowerShell:

```powershell
$env:SPOTIFY_ACCESS_TOKEN = "your temporary OAuth access token"
# config.yaml: spotify.enabled: true
.\run.ps1 -Tray
```

Tokens are never logged or stored. Expired/unauthorized API requests fail clearly; Jarvis does not silently switch to cloud AI. When Spotify integration is disabled or the environment token is absent, local Windows media sessions are used.

SQLite data is stored at `memory\jarvis.db` by default. Conversation history is bounded. Facts, preferences, and aliases require explicit requests; credential-like values are rejected. Application aliases may target only allowlisted names, and folder aliases may target only existing folders inside searchable roots.

## Package

PyInstaller 6.21 supports Python 3.13 and produces a local one-folder build:

```powershell
.\package.ps1 -InstallTools
.\dist\Jarvis\Jarvis.exe --config config.yaml --check
```

The folder includes project assets. Review absolute paths in the copied `config.yaml` before moving the package. Ollama, `gemma64`, the Piper executable, and the faster-whisper model are not downloaded or embedded automatically; configure their local paths on the target machine.

## Privacy and permissions

- All AI prompts and requested screenshots go only to the configured loopback Ollama URL.
- Explicit public web/YouTube requests send only the query or public URL to the selected website; browser cookies and logged-in content are never read.
- No telemetry or cloud AI SDK is included.
- Search is restricted to configured roots; sensitive files/folders are blocked.
- Raw microphone audio is never written to disk; temporary synthesized Piper WAV files are deleted after playback.
- Clipboard data, cookies, tokens, and passwords are never persisted.
- Short-term history and explicitly approved non-sensitive memory stay in local SQLite; use the clear/forget commands to remove them.
- Screenshots are never persisted unless debug screenshot retention is explicitly enabled.
- Low-risk tools run locally. Medium-risk tools notify. High-risk tools require local confirmation.
- Destructive, command-execution, registry, install, messaging, upload, purchase, form-submit, and password tools are absent.
- File/screen content is untrusted and cannot override the system prompt or permissions.

Logs are rotated in `logs\jarvis.log` and `logs\error.log`. Tool names, success state, connection errors, and debug stack traces are logged; raw audio, screenshots, clipboard contents, secrets, and full tool data are not.

## Common errors

- `No installed Python found`: install Python 3.13 and the Python launcher, then reopen PowerShell.
- `running scripts is disabled`: use `Set-ExecutionPolicy -Scope Process Bypass` for the current shell.
- `Cannot connect to local Ollama`: start Ollama and verify `http://localhost:11434/api/version` locally.
- `Local model 'gemma64' is unavailable`: run `ollama list`; do not pull an unrelated fallback model.
- Installed application or Steam game not found: verify its Start Menu shortcut/Steam manifest, use its full display name, or add an exact allowlist entry.
- Public web request blocked: verify `browser.web_access_enabled`, use a public HTTP/HTTPS address, and do not target localhost/private networks.
- Website section not found: include both the service and section name, for example `Vyhľadaj My Forza a choď na časť stránky, kde sú screenshoty`; sign in manually if the destination requires an account.
- YouTube returned no video: retry with a more specific title; YouTube page changes or rate limits can temporarily prevent public result extraction.
- `Path is outside searchable directories or is sensitive`: add the intended non-sensitive root to `files.searchable_directories`.
- `Whisper model 'medium' is not available locally`: run the explicit `audio.speech_to_text --download-model medium` command above or configure a local model directory.
- `Microphone recording failed`: run `python -m audio.recorder`, select a valid input, and enable Windows microphone privacy access for desktop apps.
- `Could not register global hotkey`: another application owns that combination; change it under `hotkeys` in `config.yaml`.
- `Piper executable_path is not configured`: set the executable and local voice paths, preserving each voice's `.onnx.json` file.
- `Missing wake-word assets`: run the explicit `audio.wake_word --download-model` command above; normal startup will not download them.
- Tray starts but wake detection is inactive: check the wake assets, Windows microphone privacy permission, configured microphone device, and `logs\error.log`.
- `mss is not installed`: rerun `install.ps1` or install `requirements.txt` in the project `.venv`.
- `Could not capture the active window`: restore a visible foreground window; minimized, secure-desktop, and protected windows can reject capture.
- Empty or inaccurate screen description: confirm `gemma64` image support, increase screenshot limits if text is too small, and keep debug retention disabled unless diagnosing locally.
- PDF/DOCX reader missing: run `.\.venv\Scripts\python.exe -m pip install -e ".[documents]"`.
- Window focus denied: Windows sometimes restricts foreground changes; manually activate the app once and retry.
- `No active Windows media session`: start playback in Spotify, a browser, or another GSMTC-compatible player first.
- Spotify HTTP 401/403: renew the environment access token and verify Premium/scopes; never place the token in `config.yaml`.
- Packaged build cannot find Piper/Whisper: update the packaged `config.yaml` to existing local paths; large model files are deliberately not downloaded or embedded automatically.
