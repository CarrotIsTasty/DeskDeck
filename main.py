"""
DeskDeck
--------------------
A prototype Windows control panel that lets you:
  - See every app currently playing audio and control its volume/mute individually,
    plus a master volume fader for the whole system
  - Watch live CPU usage + temp, RAM usage, and GPU usage + temp
  - Keep running quietly in the system tray instead of closing, and optionally
    launch automatically when Windows starts

WINDOWS ONLY. Relies on:
  - WASAPI (via pycaw/comtypes) for per-app audio and the system master volume
  - psutil for CPU/RAM usage
  - pynvml for GPU usage/VRAM (NVIDIA only)
  - LibreHardwareMonitorLib.dll, loaded in-process via pythonnet, for CPU temp
    (any vendor). Unlike the other options tried for this app (Core Temp,
    HWiNFO), this is embedded directly rather than run as a separate app -
    see the "CPU temperature" section below for what that requires.
  - winreg (stdlib) for the optional "start with Windows" registry entry

Install dependencies:
    pip install PyQt6 pycaw comtypes psutil pynvml pythonnet

Also required for CPU temp:
    1. Download LibreHardwareMonitor (https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)
       and copy LibreHardwareMonitorLib.dll (plus any DLLs sitting next to it
       in the release zip, e.g. HidSharp.dll) into a "libs" folder next to
       this file.
    2. This app now needs to run AS ADMINISTRATOR for real sensor values -
       reading CPU temperature requires kernel-level access, same as any of
       the standalone tools would need. main() below elevates itself
       automatically (a UAC prompt on launch) rather than requiring you to
       remember to run it elevated by hand.
    If the DLL is missing, pythonnet isn't installed, or elevation didn't
    happen, CPU temp just shows "N/A" - the rest of the app still works
    unelevated.

Run:
    python main.py
"""

import sys
import os
import json
import winreg
import ctypes
import subprocess

# Auto-relaunch via local venv if third-party modules are missing in the current Python environment
_app_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
_venv_python = os.path.join(_app_dir, "venv", "Scripts", "python.exe")
_venv_pythonw = os.path.join(_app_dir, "venv", "Scripts", "pythonw.exe")

try:
    import psutil
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QSlider, QPushButton, QScrollArea, QFrame, QTabWidget,
        QProgressBar, QCheckBox, QGraphicsDropShadowEffect, QSizePolicy,
        QSystemTrayIcon, QMenu, QMessageBox
    )
    from PyQt6.QtCore import Qt, QTimer, QRectF
    from PyQt6.QtGui import (
        QPainter, QPen, QColor, QFont, QConicalGradient, QFontMetrics,
        QIcon, QPixmap
    )
except ImportError as _err:
    if not getattr(sys, "frozen", False) and (os.path.exists(_venv_python) or os.path.exists(_venv_pythonw)):
        _target_py = _venv_pythonw if os.path.exists(_venv_pythonw) else _venv_python
        if sys.executable.lower() != _target_py.lower():
            subprocess.run([_target_py, os.path.abspath(__file__)] + sys.argv[1:])
            sys.exit(0)
    print(f"\n[DeskDeck Error] Missing dependency: {_err}")
    print("To fix this, please run: start.bat (which auto-installs dependencies)")
    print("or run in terminal: pip install -r requirements.txt\n")
    if sys.stdin and sys.stdin.isatty():
        input("Press Enter to exit...")
    sys.exit(1)

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-built .exe: use the folder the .exe lives in,
    # not the temp extraction dir (__file__ inside a frozen bundle points
    # into a throwaway _MEIPASS folder that vanishes after the app exits).
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
HIDDEN_SESSIONS_FILE = os.path.join(APP_DIR, "hidden_sessions.json")
VOLUME_PREFS_FILE = os.path.join(APP_DIR, "app_volume_prefs.json")

from pycaw.pycaw import AudioUtilities

try:
    import pynvml
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except Exception:
    NVML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Look & feel
#
# One dark, flat, "modern dashboard" theme applied app-wide via a Qt style
# sheet, plus a handful of small helpers (drop shadows, rich-text labels)
# used by the widgets below. Nothing here changes app behavior - it's all
# presentational.
# ---------------------------------------------------------------------------

ACCENT = "#7c9eff"
ACCENT_SOFT = "#5b6fd6"
BG = "#14151c"
PANEL = "#1c1e29"
CARD = "#21232f"
CARD_BORDER = "#2c2f40"
TEXT = "#e9eaf2"
TEXT_DIM = "#8b8ea3"
GOOD = "#4cd97b"
WARN = "#ffc857"
BAD = "#ff6b6b"

STYLE_SHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Segoe UI Variable", sans-serif;
}}

QWidget#Central {{
    background-color: {BG};
}}

QLabel {{
    background: transparent;
}}

QCheckBox {{
    background: transparent;
}}

QSlider {{
    background: transparent;
}}

QLabel#AppTitle {{
    color: {TEXT};
    font-size: 19pt;
    font-weight: 700;
}}

QLabel#AppSubtitle {{
    color: {TEXT_DIM};
    font-size: 9pt;
    padding-bottom: 4px;
}}

QLabel#SectionHeader {{
    color: {TEXT};
    font-size: 12pt;
    font-weight: 600;
}}

QLabel#HintLabel {{
    color: {TEXT_DIM};
    font-size: 8.5pt;
}}

QLabel#WarningLabel {{
    color: {WARN};
    font-size: 8.5pt;
}}

QFrame#Panel {{
    background-color: {PANEL};
    border: 1px solid {CARD_BORDER};
    border-radius: 14px;
}}

QFrame#AppCard {{
    background-color: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
}}

QFrame#GaugeCard {{
    background-color: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: 12px;
}}

QFrame#Divider {{
    background-color: {CARD_BORDER};
    max-height: 1px;
    border: none;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: {CARD_BORDER};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {ACCENT_SOFT};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: {CARD_BORDER};
    border-radius: 5px;
    min-width: 24px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {ACCENT_SOFT};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QCheckBox {{
    color: {TEXT_DIM};
    font-size: 9pt;
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid {CARD_BORDER};
    background: {CARD};
}}

QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}

QPushButton {{
    background-color: {CARD};
    color: {TEXT};
    border: 1px solid {CARD_BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 9pt;
}}

QPushButton:hover {{
    background-color: #2a2d3e;
    border: 1px solid {ACCENT_SOFT};
}}

QPushButton:pressed {{
    background-color: #23253320;
}}

QPushButton#RefreshButton {{
    background-color: {ACCENT_SOFT};
    border: 1px solid {ACCENT_SOFT};
    color: #ffffff;
    font-weight: 600;
}}

QPushButton#RefreshButton:hover {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
}}

QPushButton#HideButton {{
    color: {TEXT_DIM};
}}

QPushButton#MuteButton[muted="true"] {{
    background-color: #3a2430;
    border: 1px solid #6e3550;
    color: {BAD};
}}

QSlider::groove:horizontal {{
    height: 5px;
    background: #2a2d3e;
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    height: 5px;
    background: {ACCENT};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: #ffffff;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid {ACCENT};
}}

QSlider::handle:horizontal:hover {{
    border: 2px solid {ACCENT_SOFT};
}}

QSlider::groove:vertical {{
    width: 6px;
    background: #2a2d3e;
    border-radius: 3px;
}}

QSlider::handle:vertical {{
    background: {ACCENT};
    height: 14px;
    width: 30px;
    margin: 0 -12px;
    border-radius: 4px;
}}

QSlider::handle:vertical:hover {{
    background: {ACCENT_SOFT};
}}

QFrame#AppCard QPushButton {{
    font-size: 7.5pt;
    padding: 4px 2px;
}}
"""


def add_shadow(widget, blur=24, alpha=110, y_offset=6):
    """Attach a soft drop shadow to a widget - used to lift cards/panels off
    the flat background a little."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


def build_app_icon():
    """A small accent-colored rounded square with an 'M' - used for both the
    window icon and the tray icon. Generated in code so the app doesn't need
    a bundled .ico/.png asset."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", 26, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "M")
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _stable_role_key(name, pid, fallback_identifier):
    """For Electron-style apps that spawn several identically-named processes
    with different ROLES (confirmed via diagnostic: Discord runs one
    `--type=renderer` process for its main app/UI sounds, and a separate
    `--type=utility --utility-sub-type=audio.mojom.AudioService` process for
    voice-call audio) - build the hide/unhide key from those role flags in
    the process's command line instead of the per-launch session identifier.
    The role flags are the same on every launch; PIDs and
    GetSessionInstanceIdentifier() are not, which is why hiding e.g. just
    Discord's system-sound session didn't survive a restart before.

    Falls back to fallback_identifier if the command line isn't readable, or
    doesn't have a --type= flag (true for most non-Electron apps - this only
    changes behavior for apps that actually have this multi-role pattern).
    """
    try:
        cmdline = psutil.Process(pid).cmdline()
    except Exception:
        return fallback_identifier

    type_flag = None
    subtype_flag = None
    for arg in cmdline:
        if arg.startswith("--type="):
            type_flag = arg.split("=", 1)[1]
        elif arg.startswith("--utility-sub-type="):
            subtype_flag = arg.split("=", 1)[1]

    if type_flag is None:
        return fallback_identifier

    return f"{name}|type={type_flag}|subtype={subtype_flag or ''}"


def get_playback_sessions():
    """Return list of (display_name, pid, identifier, SimpleAudioVolume interface)
    for every app currently holding an audio session.

    `identifier` is normally IAudioSessionControl2.GetSessionInstanceIdentifier(),
    which WASAPI guarantees is unique PER SESSION INSTANCE. This matters for
    apps like Discord: its multiple subprocesses share the same
    GetSessionIdentifier() (that one is meant for grouping sessions from the
    same app, e.g. so a volume change applies to "the app" as a whole) -
    using that for hiding caused hiding one Discord process to hide all of
    them. GetSessionInstanceIdentifier() doesn't have that problem, but it's
    also not stable across a full app restart - so _stable_role_key() above
    upgrades it to a restart-stable, role-based key when the process's
    command line supports that (see its docstring); otherwise this falls
    back to the plain per-instance identifier, same as before.
    """
    sessions = AudioUtilities.GetAllSessions()
    result = []
    for session in sessions:
        if session.Process is None:
            continue  # system sounds session with no owning process; skip
        try:
            name = session.Process.name()
            pid = session.Process.pid
            volume_iface = session.SimpleAudioVolume
            try:
                identifier = session._ctl.GetSessionInstanceIdentifier()
            except Exception:
                identifier = f"{name}:{pid}"  # fallback: unique for this run only
            identifier = _stable_role_key(name, pid, identifier)
            result.append((name, pid, identifier, volume_iface))
        except Exception:
            continue
    return result


# ---------------------------------------------------------------------------
# Hidden-session persistence
# ---------------------------------------------------------------------------

def load_hidden_identifiers():
    if not os.path.exists(HIDDEN_SESSIONS_FILE):
        return set()
    try:
        with open(HIDDEN_SESSIONS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_hidden_identifiers(identifiers):
    try:
        with open(HIDDEN_SESSIONS_FILE, "w") as f:
            json.dump(sorted(identifiers), f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Per-app volume persistence
#
# Keyed by executable name (e.g. "discord.exe") rather than the session
# identifier, since the identifier isn't guaranteed stable across a full app
# restart but the executable name is exactly what a person thinks of as
# "this app's volume". A saved level is applied once per session instance
# (tracked by MixerTab) rather than on every poll, so it restores your
# preferred level on startup / when an app reopens without fighting you if
# you then change it again by hand.
# ---------------------------------------------------------------------------

def load_volume_prefs():
    if not os.path.exists(VOLUME_PREFS_FILE):
        return {}
    try:
        with open(VOLUME_PREFS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_volume_prefs(prefs):
    try:
        with open(VOLUME_PREFS_FILE, "w") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# "Start with Windows" (HKCU Run key - no admin rights needed)
# ---------------------------------------------------------------------------

STARTUP_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "MiniControlCenter"


def _startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script_path = os.path.abspath(__file__)
    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{interpreter}" "{script_path}"'


def _elevated_task_logon_trigger_enabled():
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", ELEVATED_TASK_NAME, "/v", "/fo", "list"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            if line.strip().startswith("Scheduled Task State"):
                return "Enabled" in line
        return False
    except Exception:
        return False


def is_startup_enabled():
    # Prefer the Scheduled Task's own "at logon" trigger, if that task has
    # been registered (see register_elevated_task()) - it starts the app
    # already elevated, with no UAC prompt at sign-in. Falls back to the
    # plain registry Run key (no admin needed to read/write, but the app
    # will then hit the UAC-prompts-every-time path once it launches).
    if elevated_task_exists():
        return _elevated_task_logon_trigger_enabled()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
            return value == _startup_command()
    except OSError:
        return False


def set_startup_enabled(enabled):
    if elevated_task_exists():
        try:
            subprocess.run(
                ["schtasks", "/change", "/tn", ELEVATED_TASK_NAME, "/enable" if enabled else "/disable"],
                capture_output=True, text=True,
            )
        except Exception:
            pass
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, _startup_command())
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_VALUE_NAME)
                except OSError:
                    pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# App state persistence: window position/size + always-on-top.
#
# (Hidden apps live in their own file, HIDDEN_SESSIONS_FILE, since they're
# keyed by session identifier rather than being simple app-wide toggles;
# per-app volume levels similarly have their own file, VOLUME_PREFS_FILE.)
#
# Geometry uses Qt's own saveGeometry()/restoreGeometry() (stored as a hex
# string) rather than hand-tracking x/y/width/height, since Qt's version
# correctly round-trips maximized state and multi-monitor placement.
# ---------------------------------------------------------------------------

APP_STATE_FILE = os.path.join(APP_DIR, "app_state.json")


def load_app_state():
    if not os.path.exists(APP_STATE_FILE):
        return {}
    try:
        with open(APP_STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_app_state(state):
    try:
        with open(APP_STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Admin elevation
#
# Reading CPU temperature needs kernel-level access, which needs this whole
# process running elevated (see the CPU temperature section below for why).
# Everything else in this app (mixer, GPU, tray, startup registry entry)
# works fine unelevated, so rather than forcing every launch through an
# elevated terminal, main() below calls ensure_elevated() once at startup.
#
# A plain "runas" elevation request (ShellExecuteW below) shows a UAC prompt
# every single time - Windows has no way to "remember" that consent for a
# regular app, by design. The one way around that is a Scheduled Task
# registered with RunLevel=Highest: once such a task exists, *triggering*
# it (schtasks /run) launches its action elevated with no prompt, because
# the trust decision was already made when the task was created (which
# itself needs one elevated action, done once via --register-task below).
#
# So ensure_elevated() tries the Scheduled Task route first (silent, but
# only works after the one-time setup), and falls back to the
# always-prompts ShellExecuteW route if that task isn't registered yet.
# Either way, if elevation isn't obtained, this copy just keeps running
# unelevated - CPU temp will show "N/A" but the rest of the app is fine.
# ---------------------------------------------------------------------------

ELEVATED_TASK_NAME = "MiniControlCenterElevated"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _elevated_task_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = os.path.abspath(__file__)
    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{interpreter}" "{script}"'


def elevated_task_exists():
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", ELEVATED_TASK_NAME],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def register_elevated_task():
    """One-time setup - run this elevated (setup_admin_task.bat -> right-click
    -> Run as administrator, or `python main.py --register-task` from an
    admin terminal). Registers a Scheduled Task ('MiniControlCenterElevated',
    RunLevel=Highest) that launches this app elevated with NO UAC prompt on
    future runs, since the trust decision is made once here instead of on
    every launch. Also given an "at logon" trigger, so "Start with Windows"
    can (once this is registered) enable/disable that trigger instead of
    prompting for UAC at every sign-in. Safe to re-run - overwrites any
    existing registration of the same task (/f)."""
    command = _elevated_task_command()
    result = subprocess.run(
        ["schtasks", "/create", "/tn", ELEVATED_TASK_NAME, "/tr", command,
         "/sc", "onlogon", "/rl", "highest", "/f"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"'{ELEVATED_TASK_NAME}' registered - future launches won't show a UAC prompt.")
        # Start disabled: the "at logon" trigger only auto-starts the app if
        # "Start with Windows" is later checked in the app itself.
        subprocess.run(["schtasks", "/change", "/tn", ELEVATED_TASK_NAME, "/disable"],
                        capture_output=True, text=True)
    else:
        print("Failed to register the task. This step itself needs to be run")
        print("elevated (right-click setup_admin_task.bat -> Run as administrator).")
        print(result.stdout)
        print(result.stderr)
    return result.returncode == 0


def launch_elevated_registration():
    """Relaunches this app elevated just long enough to run
    register_elevated_task() - the in-app equivalent of right-clicking
    setup_admin_task.bat -> Run as administrator, for people who'd rather
    not go hunting for a .bat file. Shows exactly one UAC prompt (Windows
    requires that one-time trust decision for any elevated action - no way
    around it), blocks until the elevated helper exits (it only calls
    schtasks, so this is near-instant), and returns whether the task ended
    up registered - False if the prompt was declined or something failed.
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = "--register-task"
    else:
        exe_dir = os.path.dirname(sys.executable)
        pythonw = os.path.join(exe_dir, "pythonw.exe")
        exe = pythonw if os.path.exists(pythonw) else sys.executable
        params = f'"{os.path.abspath(__file__)}" --register-task'

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p), ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p), ("hKeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong), ("hIcon", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = params
    info.nShow = SW_HIDE

    try:
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            return False  # declined the UAC prompt, or failed outright
        if info.hProcess:
            ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 15000)
            ctypes.windll.kernel32.CloseHandle(info.hProcess)
    except Exception:
        return False

    return elevated_task_exists()


def ensure_elevated():
    """If not already running elevated, try the silent Scheduled Task route
    first, then fall back to a plain elevation request (UAC prompt every
    time) if that task isn't registered. Returns without doing anything if
    already elevated."""
    if is_admin():
        return

    try:
        result = subprocess.run(
            ["schtasks", "/run", "/tn", ELEVATED_TASK_NAME],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            # The task launched an elevated copy of this app - this copy exits.
            sys.exit(0)
    except Exception:
        pass

    try:
        if getattr(sys, "frozen", False):
            args = sys.argv[1:]
        else:
            args = [os.path.abspath(__file__)] + sys.argv[1:]
        params = " ".join(f'"{a}"' for a in args)
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        if result > 32:
            # Elevated relaunch was accepted and started - let that copy be
            # the real one, this unelevated copy exits.
            sys.exit(0)
        # result <= 32 means it failed or the person clicked "No" on the UAC
        # prompt - fall through and keep running this unelevated copy.
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CPU temperature - LibreHardwareMonitorLib, embedded in-process via
# pythonnet (no separate app running in the background).
#
# Requires:
#   - `pip install pythonnet`
#   - LibreHardwareMonitorLib.dll (+ companion DLLs) in a "libs" folder next
#     to this file - see LIBS_DIR below.
#   - This process running elevated (see ensure_elevated() above) - without
#     that, the library loads fine but every sensor reads back as 0/empty.
#
# If any of the above isn't in place, get_cpu_temp()/get_ram_temp() just
# return None (shown as "N/A"), same as before - never crashes the app.
#
# RAM temp uses the same LibreHardwareMonitorLib setup, via its Memory
# hardware type. Whether it reports anything depends on the RAM itself
# having a physical thermal sensor exposed over SPD/I2C - true for some
# enthusiast/RGB desktop RAM kits, essentially never true for laptop RAM.
# So on most laptops this will legitimately just stay "N/A" even with
# everything else working correctly - that's the hardware, not a bug.
#
# GPU usage % and GPU temp DO work out of the box for NVIDIA cards via
# `pynvml`, since NVIDIA ships that access through their driver directly -
# no separate monitoring app needed for that one.
# ---------------------------------------------------------------------------

LIBS_DIR = os.path.join(APP_DIR, "libs")
LHM_DLL_PATH = os.path.join(LIBS_DIR, "LibreHardwareMonitorLib.dll")

_lhm_computer = None       # the .NET Computer object, opened once and reused
_lhm_hardware_type = None  # LibreHardwareMonitor.Hardware.HardwareType, cached after first import
_lhm_sensor_type = None    # LibreHardwareMonitor.Hardware.SensorType, cached after first import
_lhm_init_attempted = False


def _init_lhm():
    """Load pythonnet + LibreHardwareMonitorLib and open a Computer object.
    Robustly handles PyInstaller pre-initialized CLR and companion DLL dependencies."""
    global _lhm_computer, _lhm_hardware_type, _lhm_sensor_type, _lhm_init_attempted
    if _lhm_computer is not None:
        return
    if _lhm_init_attempted:
        return

    if not os.path.exists(LHM_DLL_PATH):
        return

    try:
        try:
            from pythonnet import load
            load("netfx")  # use the .NET Framework CLR on Windows
        except Exception:
            # Runtime may already be initialized (e.g. inside PyInstaller) or netfx default
            pass

        import clr
        dll_dir = os.path.dirname(os.path.abspath(LHM_DLL_PATH))
        if dll_dir not in sys.path:
            sys.path.insert(0, dll_dir)

        clr.AddReference(LHM_DLL_PATH)
        from LibreHardwareMonitor.Hardware import Computer, HardwareType, SensorType

        computer = Computer()
        computer.IsCpuEnabled = True
        computer.IsMemoryEnabled = True
        computer.IsMotherboardEnabled = True
        computer.IsControllerEnabled = True
        computer.Open()

        _lhm_computer = computer
        _lhm_hardware_type = HardwareType
        _lhm_sensor_type = SensorType
    except Exception as e:
        print(f"LHM init exception: {e}")
        _lhm_init_attempted = True
        return


def _collect_sensors_recursive(hardware, target_type, temps):
    """Recursively collect temperature sensors from hardware and any SubHardware."""
    try:
        if hardware.HardwareType == target_type:
            hardware.Update()
            for sensor in hardware.Sensors:
                if sensor.SensorType == _lhm_sensor_type.Temperature:
                    val = sensor.Value
                    if val is not None:
                        try:
                            fval = float(val)
                            if 10.0 <= fval <= 125.0:
                                temps.append(fval)
                        except (ValueError, TypeError):
                            pass

        if hasattr(hardware, "SubHardware"):
            for sub in hardware.SubHardware:
                _collect_sensors_recursive(sub, target_type, temps)
    except Exception:
        pass


def _lhm_max_temp(hardware_type_name):
    """Highest current temperature sensor reading among all hardware of the
    given LibreHardwareMonitor.Hardware.HardwareType (looked up by name, e.g.
    "Cpu" or "Memory"), in whole degrees C, or None."""
    _init_lhm()
    if _lhm_computer is None:
        return None

    target_type = getattr(_lhm_hardware_type, hardware_type_name, None)
    if target_type is None:
        return None

    temps = []
    try:
        for hardware in _lhm_computer.Hardware:
            _collect_sensors_recursive(hardware, target_type, temps)
    except Exception:
        return None

    if not temps:
        # Fallback for laptops where CPU temp is exposed under Motherboard / SuperIO / EC
        if hardware_type_name == "Cpu":
            try:
                for hardware in _lhm_computer.Hardware:
                    hardware.Update()
                    for sensor in hardware.Sensors:
                        if sensor.SensorType == _lhm_sensor_type.Temperature and sensor.Value is not None:
                            s_name = str(sensor.Name).lower()
                            if any(k in s_name for k in ["cpu", "core", "package", "processor", "tjmax", "soc"]):
                                try:
                                    fval = float(sensor.Value)
                                    if 10.0 <= fval <= 125.0:
                                        temps.append(fval)
                                except (ValueError, TypeError):
                                    pass
            except Exception:
                pass

    if not temps:
        return None
    return int(round(max(temps)))


def _get_wmi_cpu_temp_fallback():
    """Fallback CPU temperature via Windows WMI ACPI thermal zone if available."""
    try:
        import win32com.client
        wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\wmi")
        results = wmi.ExecQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature")
        temps = []
        for item in results:
            raw = item.CurrentTemperature
            if raw and raw > 2732:
                # Tenths of Kelvin to Celsius
                celsius = (raw - 2732) / 10.0
                if 10.0 <= celsius <= 125.0:
                    temps.append(celsius)
        if temps:
            return int(round(max(temps)))
    except Exception:
        pass
    return None


def get_cpu_temp():
    temp = _lhm_max_temp("Cpu")
    if temp is None:
        temp = _get_wmi_cpu_temp_fallback()
    return temp


def get_gpu_temp():
    if NVML_AVAILABLE:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            return pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        except Exception:
            pass
    return None


def get_ram_temp():
    return _lhm_max_temp("Memory")


# ---------------------------------------------------------------------------
# CPU / GPU model name - cosmetic only, shown under the gauge labels.
#
# CPU name comes straight from the registry (ProcessorNameString), which
# Windows always has available with no admin rights and no dependency on the
# LibreHardwareMonitorLib/pythonnet setup above - so it works even if that
# setup is missing or CPU temp is showing "N/A".
#
# GPU name uses the same pynvml already in use for GPU usage/temp, so it has
# the same NVIDIA-only limitation - stays blank (name just isn't shown) for
# AMD/Intel GPUs.
#
# Both are looked up once and cached, since a model name doesn't change
# during a run.
# ---------------------------------------------------------------------------

_cpu_name_cache = None
_gpu_name_cache = None


def get_cpu_name():
    global _cpu_name_cache
    if _cpu_name_cache is not None:
        return _cpu_name_cache
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            _cpu_name_cache = name.strip()
    except Exception:
        _cpu_name_cache = ""
    return _cpu_name_cache


def get_gpu_name():
    global _gpu_name_cache
    if _gpu_name_cache is not None:
        return _gpu_name_cache
    _gpu_name_cache = ""
    if NVML_AVAILABLE:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            raw = pynvml.nvmlDeviceGetName(handle)
            _gpu_name_cache = raw.decode() if isinstance(raw, bytes) else raw
        except Exception:
            pass
    return _gpu_name_cache


# ---------------------------------------------------------------------------
# UI: single app volume channel strip
# ---------------------------------------------------------------------------

class AppVolumeRow(QFrame):
    """One channel strip in the mixer: a vertical fader (push up for
    louder, just like a DJ mixer channel), the app name/PID above it,
    live % below it, and mute/hide controls at the bottom."""

    def __init__(self, name, pid, identifier, volume_iface, on_hide=None, on_volume_change=None):
        super().__init__()
        self.name = name
        self.pid = pid
        self.identifier = identifier
        self.volume_iface = volume_iface
        self.on_hide = on_hide
        self.on_volume_change = on_volume_change

        self.setObjectName("AppCard")
        self.setFixedWidth(132)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 10)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        name_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        elided_name = QFontMetrics(name_font).elidedText(name, Qt.TextElideMode.ElideRight, 108)
        label = QLabel(
            f"<div align='center'><span style='font-size:9pt;font-weight:600;color:{TEXT};'>{elided_name}</span>"
            f"<br><span style='font-size:7.5pt;color:{TEXT_DIM};'>PID {pid}</span></div>"
        )
        label.setToolTip(name)
        label.setWordWrap(False)
        label.setFixedWidth(112)
        label.setFixedHeight(36)
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.setFixedHeight(110)
        self.slider.setToolTip("Push up for louder, like a mixer channel fader")
        try:
            current = volume_iface.GetMasterVolume()
            self.slider.setValue(int(current * 100))
        except Exception:
            self.slider.setValue(100)
        self.slider.valueChanged.connect(self.set_volume)
        layout.addWidget(self.slider, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.pct_label = QLabel(f"{self.slider.value()}%")
        self.pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pct_label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; font-weight: 600;")
        layout.addWidget(self.pct_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.mute_btn = QPushButton()
        self.mute_btn.setObjectName("MuteButton")
        self.mute_btn.setFixedWidth(54)
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute_btn.clicked.connect(self.toggle_mute)
        btn_row.addWidget(self.mute_btn)

        hide_btn = QPushButton("Hide")
        hide_btn.setObjectName("HideButton")
        hide_btn.setFixedWidth(54)
        hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        hide_btn.setToolTip("Hide this entry permanently (e.g. a duplicate Discord process)")
        hide_btn.clicked.connect(self.hide_session)
        btn_row.addWidget(hide_btn)

        layout.addLayout(btn_row)

        self.refresh_mute_label()

    def set_volume(self, value):
        try:
            self.volume_iface.SetMasterVolume(value / 100.0, None)
            self.pct_label.setText(f"{value}%")
        except Exception:
            pass
        if self.on_volume_change:
            self.on_volume_change(self.name, value)

    def toggle_mute(self):
        try:
            muted = bool(self.volume_iface.GetMute())
            self.volume_iface.SetMute(0 if muted else 1, None)
            self.refresh_mute_label()
        except Exception:
            pass

    def refresh_mute_label(self):
        try:
            muted = bool(self.volume_iface.GetMute())
        except Exception:
            muted = False
        self.mute_btn.setText("Unmute" if muted else "Mute")
        self.mute_btn.setProperty("muted", "true" if muted else "false")
        self.mute_btn.style().unpolish(self.mute_btn)
        self.mute_btn.style().polish(self.mute_btn)

    def hide_session(self):
        if self.on_hide:
            self.on_hide(self.identifier)


# ---------------------------------------------------------------------------
# UI: Mixer tab
# ---------------------------------------------------------------------------

class MixerTab(QWidget):
    def __init__(self):
        super().__init__()
        self.hidden_identifiers = load_hidden_identifiers()
        self.volume_prefs = load_volume_prefs()
        self.applied_pref_identifiers = set()
        self.show_hidden = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("App Volume Mixer")
        title.setObjectName("SectionHeader")
        header.addWidget(title)
        header.addStretch()

        self.show_hidden_checkbox = QCheckBox("Show hidden")
        self.show_hidden_checkbox.setToolTip("Reveal hidden entries so you can unhide them")
        self.show_hidden_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_hidden_checkbox.stateChanged.connect(self.toggle_show_hidden)
        header.addWidget(self.show_hidden_checkbox)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("RefreshButton")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self.rebuild_rows)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        # Channels sit side by side, like a real mixer console - Master first,
        # then a divider, then one channel per app - each with its own
        # vertical fader; scrolls sideways if there are a lot of them.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # Was ScrollBarAlwaysOff - with that, resizing the window shorter
        # than one full channel strip (name/slider/%/Mute/Hide) silently
        # clipped the bottom of every row with no way to reach it. This
        # makes the window height fully dynamic - resize to whatever you
        # want, and if a row doesn't fully fit, this scrollbar appears
        # instead of losing content.
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.container = QWidget()
        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(4, 4, 4, 4)
        self.container_layout.setSpacing(10)
        self.container_layout.addStretch()
        scroll.setWidget(self.container)
        outer.addWidget(scroll)

        self.rebuild_rows()

        # periodic refresh so newly-opened apps show up automatically
        self.timer = QTimer()
        self.timer.timeout.connect(self.rebuild_rows)
        self.timer.start(4000)

    def toggle_show_hidden(self, state):
        self.show_hidden = bool(state)
        self.rebuild_rows()

    def hide_identifier(self, identifier):
        self.hidden_identifiers.add(identifier)
        save_hidden_identifiers(self.hidden_identifiers)
        self.rebuild_rows()

    def unhide_identifier(self, identifier):
        self.hidden_identifiers.discard(identifier)
        save_hidden_identifiers(self.hidden_identifiers)
        self.rebuild_rows()

    def save_volume_pref(self, name, value):
        self.volume_prefs[name] = value
        save_volume_prefs(self.volume_prefs)

    def rebuild_rows(self):
        # clear existing app rows
        while self.container_layout.count() > 1:
            item = self.container_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        sessions = get_playback_sessions()

        if not self.show_hidden:
            sessions = [s for s in sessions if s[2] not in self.hidden_identifiers]

        if not sessions:
            msg = "No apps are currently playing audio." if not self.hidden_identifiers else \
                  "No visible apps. Check 'Show hidden' if you hid something by mistake."
            empty = QLabel(msg)
            empty.setObjectName("HintLabel")
            empty.setContentsMargins(4, 8, 4, 8)
            self.container_layout.insertWidget(0, empty)
            return

        for name, pid, identifier, iface in sessions:
            # Restore a saved volume level once per session instance, so
            # relaunching an app (or the whole control center) brings back
            # the level you left it at - without fighting a manual change
            # you make afterwards through this app or Windows' own mixer.
            if identifier not in self.applied_pref_identifiers:
                self.applied_pref_identifiers.add(identifier)
                saved = self.volume_prefs.get(name)
                if saved is not None:
                    try:
                        iface.SetMasterVolume(saved / 100.0, None)
                    except Exception:
                        pass

            if self.show_hidden and identifier in self.hidden_identifiers:
                row = AppVolumeRow(
                    name, pid, identifier, iface,
                    on_hide=self.unhide_identifier, on_volume_change=self.save_volume_pref,
                )
                # relabel the hide button to "Unhide" for already-hidden rows
                for btn in row.findChildren(QPushButton):
                    if btn.text() == "Hide":
                        btn.setText("Unhide")
            else:
                row = AppVolumeRow(
                    name, pid, identifier, iface,
                    on_hide=self.hide_identifier, on_volume_change=self.save_volume_pref,
                )
            self.container_layout.insertWidget(self.container_layout.count() - 1, row, 0, Qt.AlignmentFlag.AlignTop)


# ---------------------------------------------------------------------------
# UI: System monitor tab
# ---------------------------------------------------------------------------

class GaugeWidget(QWidget):
    """A speedometer-style circular gauge. Draws a 270-degree arc track with a
    colored fill proportional to `value`, and the percentage centered inside."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.setMinimumSize(130, 130)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def setValue(self, value):
        self.value = max(0.0, min(100.0, value))
        self.update()

    def _color_for_ratio(self, ratio):
        if ratio < 0.6:
            return QColor(GOOD)
        elif ratio < 0.85:
            return QColor(WARN)
        return QColor(BAD)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        thickness = max(9, int(side * 0.1))
        margin = thickness + 4
        rect = QRectF(
            (self.width() - side) / 2 + margin / 2,
            (self.height() - side) / 2 + margin / 2,
            side - margin,
            side - margin,
        )

        start_angle = 225   # bottom-left, in Qt's counterclockwise-from-3-o'clock system
        total_span = -270   # sweep clockwise over the top to bottom-right

        # background track
        pen_bg = QPen(QColor("#2a2d3e"), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, start_angle * 16, total_span * 16)

        # filled portion, with a soft gradient toward the fill color
        ratio = self.value / 100.0
        fill_color = self._color_for_ratio(ratio)
        gradient = QConicalGradient(rect.center(), start_angle)
        gradient.setColorAt(0.0, QColor(ACCENT))
        gradient.setColorAt(1.0, fill_color)
        pen_fg = QPen(gradient, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        painter.drawArc(rect, start_angle * 16, int(total_span * ratio * 16))

        # percentage text, centered
        painter.setPen(QColor(TEXT))
        font = QFont("Segoe UI", max(10, int(side * 0.15)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{int(round(self.value))}%")


class MetricGauge(QWidget):
    """Gauge + label + temperature, stacked: [gauge with % in the middle] / [CPU|RAM|GPU] / [temp],
    presented as a small card."""

    def __init__(self, name):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("GaugeCard")
        add_shadow(card, blur=20, alpha=90, y_offset=4)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(4)

        self.gauge = GaugeWidget()
        layout.addWidget(self.gauge, alignment=Qt.AlignmentFlag.AlignCenter)

        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont("Segoe UI", 10)
        f.setBold(True)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105)
        name_label.setFont(f)
        name_label.setStyleSheet(f"color: {TEXT}; background: transparent;")
        layout.addWidget(name_label)

        # Model name (e.g. "Ryzen 5 5600H") - set once via set_detail_text(),
        # not on every poll, since it doesn't change during a run. Elided to
        # fit the card, with the full name always available as a tooltip.
        self.detail_label = QLabel("")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 7.5pt; background: transparent;")
        self.detail_label.setVisible(False)
        layout.addWidget(self.detail_label)

        self.temp_label = QLabel("-- °C")
        self.temp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.temp_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 8.5pt; background: transparent;")
        layout.addWidget(self.temp_label)

        # Optional extra line below the temp - only RAM uses this today, for
        # a "7.4 / 16.0 GB" used/total readout. Empty and taking no visible
        # space for CPU/GPU, which don't call set_extra_text().
        self.extra_label = QLabel("")
        self.extra_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.extra_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 8.5pt; background: transparent;")
        self.extra_label.setVisible(False)
        layout.addWidget(self.extra_label)

    def set_usage(self, value):
        self.gauge.setValue(value)

    def set_detail_text(self, text):
        # Full text is kept so it can be re-elided on resize instead of
        # elided once at whatever width the card happened to be at the time.
        self._detail_full_text = text or ""
        if not text:
            self.detail_label.setVisible(False)
            return
        self.detail_label.setToolTip(text)
        self.detail_label.setVisible(True)
        self._reelide_detail_text()

    def _reelide_detail_text(self):
        text = getattr(self, "_detail_full_text", "")
        if not text:
            return
        # Elide to the label's own current width, not a fixed guess - this
        # is what makes widening the window actually reveal more of the
        # name instead of staying truncated at the same point.
        width = self.detail_label.width()
        if width <= 0:
            width = self.width() - 24  # fallback before the first layout pass
        metrics = QFontMetrics(self.detail_label.font())
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(width, 0))
        self.detail_label.setText(elided)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reelide_detail_text()

    def set_temp_text(self, text):
        self.temp_label.setText(text)

    def set_extra_text(self, text):
        self.extra_label.setText(text)
        self.extra_label.setVisible(bool(text))


class SystemTab(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        header = QLabel("System Monitor")
        header.setObjectName("SectionHeader")
        outer.addWidget(header)

        gauges_row = QHBoxLayout()
        gauges_row.setSpacing(12)
        self.cpu_gauge = MetricGauge("CPU")
        self.ram_gauge = MetricGauge("RAM")
        self.gpu_gauge = MetricGauge("GPU")
        gauges_row.addWidget(self.cpu_gauge)
        gauges_row.addWidget(self.ram_gauge)
        gauges_row.addWidget(self.gpu_gauge)
        outer.addLayout(gauges_row)

        self.cpu_gauge.set_detail_text(get_cpu_name())
        self.gpu_gauge.set_detail_text(get_gpu_name())

        if not NVML_AVAILABLE:
            warn = QLabel("GPU usage unavailable (install pynvml for NVIDIA GPUs)")
            warn.setObjectName("WarningLabel")
            outer.addWidget(warn)

        self.cpu_temp_hint = QLabel(
            "CPU temp unavailable - check libs/LibreHardwareMonitorLib.dll is present "
            "and that the elevation prompt on launch was accepted"
        )
        self.cpu_temp_hint.setObjectName("WarningLabel")
        self.cpu_temp_hint.setVisible(False)
        outer.addWidget(self.cpu_temp_hint)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)
        self.update_stats()

    def update_stats(self):
        self.cpu_gauge.set_usage(psutil.cpu_percent())

        vm = psutil.virtual_memory()
        self.ram_gauge.set_usage(vm.percent)
        used_gb = vm.used / (1024 ** 3)
        total_gb = vm.total / (1024 ** 3)
        self.ram_gauge.set_extra_text(f"{used_gb:.1f} / {total_gb:.1f} GB")

        cpu_temp = get_cpu_temp()
        self.cpu_gauge.set_temp_text(f"{cpu_temp} °C" if cpu_temp is not None else "N/A")
        self.cpu_temp_hint.setVisible(cpu_temp is None)

        gpu_temp = get_gpu_temp()
        self.gpu_gauge.set_temp_text(f"{gpu_temp} °C" if gpu_temp is not None else "N/A")

        ram_temp = get_ram_temp()
        self.ram_gauge.set_temp_text(f"{ram_temp} °C" if ram_temp is not None else "N/A")

        if NVML_AVAILABLE:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                self.gpu_gauge.set_usage(util.gpu)
            except Exception:
                pass
        else:
            self.gpu_gauge.set_usage(0)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class ControlCenter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeskDeck")
        self.setWindowIcon(build_app_icon())
        self.resize(700, 700)
        self.setMinimumSize(560, 560)

        self._saved_state = load_app_state()
        geometry_hex = self._saved_state.get("geometry_hex")
        if geometry_hex:
            try:
                self.restoreGeometry(bytes.fromhex(geometry_hex))
            except Exception:
                pass

        central = QWidget()
        central.setObjectName("Central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(16)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("DeskDeck")
        title.setObjectName("AppTitle")

        subtitle_row = QHBoxLayout()
        subtitle = QLabel("Live system stats & per-app audio control")
        subtitle.setObjectName("AppSubtitle")
        subtitle_row.addWidget(subtitle)
        subtitle_row.addStretch()

        self.always_on_top_checkbox = QCheckBox("Always on top")
        self.always_on_top_checkbox.setToolTip("Keep this window above all others, like PowerToys' Always on Top")
        self.always_on_top_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        was_always_on_top = self._saved_state.get("always_on_top", False)
        self.always_on_top_checkbox.setChecked(was_always_on_top)
        if was_always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.always_on_top_checkbox.stateChanged.connect(self.toggle_always_on_top)
        subtitle_row.addWidget(self.always_on_top_checkbox)

        self.startup_checkbox = QCheckBox("Start with Windows")
        self.startup_checkbox.setToolTip("Launch DeskDeck automatically when you sign in")
        self.startup_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.startup_checkbox.setChecked(is_startup_enabled())
        self.startup_checkbox.stateChanged.connect(self.toggle_startup)
        subtitle_row.addWidget(self.startup_checkbox)

        # One-time setup so startup (and every other launch) doesn't show a
        # UAC prompt, and CPU temp works - the in-app alternative to
        # right-clicking setup_admin_task.bat -> Run as administrator.
        # Hidden once that's already been done (elevated_task_exists()).
        self.enable_silent_startup_button = QPushButton("Enable silent startup")
        self.enable_silent_startup_button.setToolTip(
            "One-time setup (needs a single admin approval) so DeskDeck never "
            "shows a Windows permission prompt again, and CPU temperature works"
        )
        self.enable_silent_startup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.enable_silent_startup_button.setVisible(not elevated_task_exists())
        self.enable_silent_startup_button.clicked.connect(self.enable_silent_startup)
        subtitle_row.addWidget(self.enable_silent_startup_button)

        title_box.addWidget(title)
        title_box.addLayout(subtitle_row)
        layout.addLayout(title_box)

        system_panel = QFrame()
        system_panel.setObjectName("Panel")
        add_shadow(system_panel, blur=28, alpha=100, y_offset=6)
        system_panel_layout = QVBoxLayout(system_panel)
        system_panel_layout.setContentsMargins(16, 16, 16, 16)
        system_tab = SystemTab()
        system_panel_layout.addWidget(system_tab)
        layout.addWidget(system_panel, 0)

        mixer_panel = QFrame()
        mixer_panel.setObjectName("Panel")
        add_shadow(mixer_panel, blur=28, alpha=100, y_offset=6)
        mixer_panel_layout = QVBoxLayout(mixer_panel)
        mixer_panel_layout.setContentsMargins(16, 16, 16, 16)
        mixer_tab = MixerTab()
        mixer_panel_layout.addWidget(mixer_tab)
        layout.addWidget(mixer_panel, 0)
        layout.addStretch()

        self.setCentralWidget(central)

        self._setup_tray()

    def toggle_startup(self, state):
        set_startup_enabled(bool(state))

    def enable_silent_startup(self):
        reply = QMessageBox.question(
            self, "Enable silent startup",
            "Windows will ask you to approve this once (an admin permission "
            "prompt).\n\nAfter that, DeskDeck can start with no prompts at "
            "all, and CPU temperature readings will work.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if launch_elevated_registration():
            self.enable_silent_startup_button.setVisible(False)
            QMessageBox.information(
                self, "Done",
                "Silent startup is enabled. You can now check "
                "'Start with Windows' with no more prompts.",
            )
        else:
            QMessageBox.warning(
                self, "Not enabled",
                "That wasn't approved, so nothing changed. You can try "
                "again anytime - DeskDeck works fine without it, just with "
                "an admin prompt on each launch and no CPU temperature.",
            )

    def toggle_always_on_top(self, state):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(state))
        self.show()  # changing window flags requires re-showing to take effect

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(build_app_icon(), self)
        self.tray_icon.setToolTip("DeskDeck")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show DeskDeck")
        show_action.triggered.connect(self.show_and_raise)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_and_raise()

    def show_and_raise(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _persist_state(self):
        save_app_state({
            "geometry_hex": bytes(self.saveGeometry()).hex(),
            "always_on_top": self.always_on_top_checkbox.isChecked(),
        })

    def _quit(self):
        self._persist_state()
        QApplication.instance().quit()

    def closeEvent(self, event):
        # Closing the window just tucks the app into the tray - it keeps
        # running (audio mixer + system monitor stay live) until you pick
        # "Quit" from the tray icon's menu.
        self._persist_state()
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "DeskDeck",
            "Still running in the background. Right-click the tray icon to quit.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )


def main():
    ensure_elevated()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE_SHEET)
    app.setQuitOnLastWindowClosed(False)  # closing to tray shouldn't end the app
    window = ControlCenter()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    if "--register-task" in sys.argv:
        # One-time setup path - see register_elevated_task()'s docstring.
        # Must itself be run elevated (setup_admin_task.bat handles that).
        register_elevated_task()
    else:
        main()
