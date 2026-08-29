# Mini Control Center — Prototype

A Windows-only desktop app (PyQt6), single window, dark "mixer console" look. Everything except CPU temp needs no extra software or admin rights; CPU temp needs one DLL dropped in locally and the app to run elevated (details below):

- **App volume mixer**, styled like a DJ mixer — every app currently playing audio gets its own vertical fader (push up for louder) plus mute/hide (WASAPI via `pycaw`). Apps you don't care about can be hidden with the **Hide** button. Hidden state persists across restarts (`hidden_sessions.json`). For most apps this is matched by `GetSessionInstanceIdentifier()`, unique per session instance — hiding one process doesn't hide all of an app's processes. For apps like Discord that run several identically-named processes with genuinely different *roles* (its main app process vs. a separate audio-service process specifically for voice calls), `_stable_role_key()` upgrades the match to those processes' `--type=`/`--utility-sub-type=` command-line flags instead, which stay the same across restarts — so e.g. hiding just Discord's system-sound session (and keeping its voice-call session visible) now survives a reboot instead of both reappearing. Check **Show hidden** to reveal and unhide entries later.
- **Per-app volume persistence** (`app_volume_prefs.json`, keyed by executable name) — the level you leave an app's fader at is restored automatically the next time that app plays audio, including after restarting Mini Control Center. It's applied once per session instance, so it won't fight you if you then change the level again by hand.
- **CPU / RAM / GPU gauges** — speedometer-style dials with usage % centered, the label underneath, and temperature under that where available.
- **System tray** — closing the window tucks the app into the tray instead of quitting (mixer + gauges keep running); right-click the tray icon for Show / Quit, or double-click it to bring the window back.
- **Start with Windows** — a checkbox next to the title writes/removes a `HKCU\...\Run` registry entry, no admin rights needed.
- **Always on top** — a checkbox next to the title pins the window above all others, like PowerToys' Always on Top.
- **Remembers your settings** — window position/size and the Always on top choice (`app_state.json`) are saved whenever you close the window or quit from the tray, and restored on the next launch. Hidden apps (`hidden_sessions.json`) and per-app volume levels (`app_volume_prefs.json`) are saved the moment you change them, as noted above. "Start with Windows" doesn't need its own save file — it just reflects whatever the registry currently says.

## Why this couldn't be run live for you

Built in a Linux sandbox with no audio hardware, no GPU, and no Windows COM/WASAPI stack, so it can't be executed there. Run it on your own Windows machine.

## Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Or just double-click `start.bat` once it's set up. **Expect a UAC prompt** on launch — the app tries to elevate itself automatically (see "About the temperature readings" below). If you click "No", the app still opens, just without CPU temp.

Requires Python 3.9+ on Windows 10/11.

**For CPU temp specifically**, two extra one-time steps:

1. Download [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases) and copy `LibreHardwareMonitorLib.dll` (plus any DLLs sitting next to it in the release zip, e.g. `HidSharp.dll`) into a `libs` folder next to `main.py`.
2. Right-click `setup_admin_task.bat` → **Run as administrator**, and follow the prompt. This registers a Scheduled Task that lets the app elevate itself **without a UAC prompt on every future launch** (see below for why this step exists and what it does).

Skipping either step is fine — the rest of the app still runs, CPU temp just shows "N/A" (step 1 missing) or you'll get a UAC prompt every launch instead of none (step 2 skipped).

## About the temperature readings

- **GPU usage % and GPU temp** work out of the box for **NVIDIA cards only**, via `pynvml`, which talks to NVIDIA's driver directly — no extra software needed.
- **CPU temp** is read via **LibreHardwareMonitorLib.dll**, loaded directly in-process through `pythonnet` — no separate monitoring app running in the background. Two things tried and dropped first: Core Temp wouldn't launch on this machine, and HWiNFO's Shared Memory Support (needed for another app to read its data) turned out to be Pro-only. Embedding the library directly avoids depending on either.

  The catch: reading real hardware sensors needs kernel-level access, so **this whole app now needs to run elevated** — not just a separate background tool, since there is no separate tool anymore. `main()` calls `ensure_elevated()` on startup; if that's declined (or elevation otherwise fails), the app keeps running unelevated with CPU temp just showing "N/A" (a small hint appears under the gauges in that case) rather than refusing to start.
- **RAM temp always shows N/A.** Windows has no built-in API for it, and it's not something planned to add.

## Avoiding a UAC prompt on every launch

A plain elevation request always shows a UAC prompt — Windows has no way for a regular app to make that a one-time decision. The workaround is a **Scheduled Task** created with "Run with highest privileges": once such a task exists, *triggering* it launches its action elevated with no prompt at all, because the trust decision was already made when the task itself was created (which does need one elevated action, done once).

That's what `setup_admin_task.bat` does (see Setup above) — it registers a task named `MiniControlCenterElevated`. After that:

- Launching the app (`start.bat` / `python main.py`) tries that task first (silent), and only falls back to a plain UAC-prompting elevation request if the task isn't registered.
- **Start with Windows** switches from writing a registry Run key to enabling/disabling that same task's "at logon" trigger, so auto-start at sign-in is silent too, instead of prompting for UAC right after login.

Skip `setup_admin_task.bat` entirely if you're fine with a UAC prompt each time — nothing else about the app requires this step.

## Known limitations / next steps

1. **AMD/Intel GPU usage %** isn't covered by `pynvml` (NVIDIA-only).
2. **Polling-based app mixer** — refreshes every 4 seconds to detect new audio sessions. For instant detection you'd hook `IAudioSessionNotification` callbacks instead.
3. **No system master volume / output device switcher** — only per-app volume is controllable right now. A master fader (system-wide volume via `IAudioEndpointVolume`) was tried and removed; switching *which* device is default (e.g. speakers ↔ headphones) would additionally need an undocumented COM interface (`IPolicyConfig`) that's fragile across Windows versions.
4. **No global hotkeys** — mute/volume nudge keyboard shortcuts only work while the window has focus.
5. **No historical graphs** — live numbers only (like Task Manager). Could plot rolling CPU/GPU/temp history with `pyqtgraph`.
6. **The Scheduled Task setup hasn't been tested end-to-end on your machine yet** — `setup_admin_task.bat` → the silent elevation on relaunch → "Start with Windows" using the task's logon trigger. Each piece works from documented Windows behavior, but this specific chain is new; if a UAC prompt still shows up after running the setup script, or "Start with Windows" behaves oddly, that's the first place to look.

## Rough architecture

```
main.py
├── is_admin / ensure_elevated — elevates on launch (needed for CPU temp): tries the silent
│   Scheduled Task route first, falls back to a UAC-prompting request, falls back further to
│   running unelevated (CPU temp = N/A) if that's declined
├── register_elevated_task / elevated_task_exists — one-time setup (--register-task, called by
│   setup_admin_task.bat) that creates the 'MiniControlCenterElevated' Scheduled Task
├── Audio helpers (pycaw) — session enumeration for the mixer; _stable_role_key gives
│   restart-stable hide/unhide identities to same-named-but-different-role processes
│   (e.g. Discord's main app vs. its voice-call audio-service process)
├── _init_lhm / get_cpu_temp — loads LibreHardwareMonitorLib.dll in-process via pythonnet (libs/),
│   reports the highest current CPU temperature sensor
├── get_gpu_temp / get_ram_temp — GPU via pynvml (NVIDIA); RAM always None
├── AppVolumeRow — one vertical-fader channel strip per audio-producing app
├── MixerTab — horizontally scrolling row of channel strips, auto-refreshing, with volume-pref persistence
├── GaugeWidget / MetricGauge — speedometer-style dial + label + temp
├── SystemTab — CPU/RAM/GPU gauges, combined with MixerTab in one window (see ControlCenter)
├── build_app_icon — generates the window/tray icon in code (no bundled asset file)
├── is_startup_enabled / set_startup_enabled — "Start with Windows": toggles the Scheduled Task's
│   logon trigger if it's registered, else falls back to a plain HKCU Run-key entry
├── load_app_state / save_app_state — window geometry + Always on top (app_state.json)
└── ControlCenter — main window; closeEvent hides to the system tray instead of quitting,
    saving state (_persist_state) on the way

libs/ — LibreHardwareMonitorLib.dll (+ companion DLLs) go here; not bundled, see Setup
setup_admin_task.bat — ONE-TIME, run as Administrator: registers the Scheduled Task above
start.bat — activates venv, runs main.py (silent if setup_admin_task.bat was run; UAC prompt otherwise)
```
