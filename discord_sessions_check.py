"""
Standalone diagnostic: inspect every discord.exe audio-playback session and
its underlying process, to find something that reliably tells the two apart
(e.g. "system sounds" vs "voice call") in a way that survives a PID change
across restarts - unlike GetSessionInstanceIdentifier(), which is what Mini
Control Center currently keys "Hide" on.

For useful output, have Discord doing BOTH things at once when you run this:
  - actually in a voice call (so the voice audio session exists)
  - and something that plays a Discord notification/UI sound around the same
    time (or just have Discord's own UI sounds active)

Usage:
    venv\\Scripts\\activate
    python discord_sessions_check.py
"""

import ctypes
from ctypes import wintypes

import psutil
from pycaw.pycaw import AudioUtilities

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def pids_with_visible_windows():
    """PIDs that own at least one visible top-level window - a rough proxy
    for 'this is the main app window process', not a background helper."""
    pids = set()

    def callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                pids.add(pid.value)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return pids


def main():
    sessions = AudioUtilities.GetAllSessions()
    windowed_pids = pids_with_visible_windows()

    found_any = False
    for session in sessions:
        if session.Process is None:
            continue
        try:
            name = session.Process.name()
        except Exception:
            continue
        if name.lower() != "discord.exe":
            continue

        found_any = True
        pid = session.Process.pid
        print(f"--- discord.exe, PID {pid} ---")

        try:
            print(f"  GetSessionIdentifier():         {session._ctl.GetSessionIdentifier()!r}")
        except Exception as e:
            print(f"  GetSessionIdentifier(): (failed: {e!r})")
        try:
            print(f"  GetSessionInstanceIdentifier(): {session._ctl.GetSessionInstanceIdentifier()!r}")
        except Exception as e:
            print(f"  GetSessionInstanceIdentifier(): (failed: {e!r})")

        try:
            proc = psutil.Process(pid)
            print(f"  Parent PID: {proc.ppid()}")
            print(f"  Command line:")
            for arg in proc.cmdline():
                print(f"    {arg!r}")
        except Exception as e:
            print(f"  psutil lookup failed: {e!r}")

        print(f"  Owns a visible top-level window: {pid in windowed_pids}")
        print()

    if not found_any:
        print("No discord.exe audio sessions found. Make sure Discord is running")
        print("and actually producing sound (in a call, or with UI sounds active),")
        print("then re-run this.")
        return

    print("Please paste this whole output back. Looking for: does 'Command line'")
    print("differ between the two PIDs (e.g. a --type=... flag), and/or does only")
    print("one of them own a visible window?")


if __name__ == "__main__":
    main()
