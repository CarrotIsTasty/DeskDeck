"""
Standalone LibreHardwareMonitorLib diagnostic.

Checks that pythonnet can load LibreHardwareMonitorLib.dll in-process and
read real CPU temperature sensors, before this gets wired into the full
DeskDeck app.

IMPORTANT: run this AS ADMINISTRATOR (right-click the terminal / this
script -> "Run as administrator", or launch an elevated cmd/PowerShell
first). Without elevation, LibreHardwareMonitorLib will load fine but
sensor readings usually come back empty/zero - that's expected, not a bug,
and elevation is required for the real app too.

Requires:
    pip install pythonnet
And LibreHardwareMonitorLib.dll (plus its companion DLLs, e.g. HidSharp.dll)
copied into the "libs" folder next to this script.

Usage:
    venv\\Scripts\\activate
    python lhm_check.py
"""

import ctypes
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LIBS_DIR = os.path.join(APP_DIR, "libs")
DLL_PATH = os.path.join(LIBS_DIR, "LibreHardwareMonitorLib.dll")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def main():
    print("--- Step 0: admin check ---")
    if is_admin():
        print("Running elevated - good.\n")
    else:
        print("NOT running as Administrator. Sensor values will likely come back")
        print("empty even if everything else works. Re-run this from an elevated")
        print("terminal (or right-click -> Run as administrator) for a real test.\n")

    print("--- Step 1: find the DLL ---")
    if not os.path.exists(DLL_PATH):
        print(f"NOT FOUND: {DLL_PATH}")
        print("Copy LibreHardwareMonitorLib.dll (and any DLLs next to it in the")
        print("release zip, e.g. HidSharp.dll) into the 'libs' folder next to this")
        print("script, then re-run.")
        return
    print(f"Found: {DLL_PATH}\n")

    print("--- Step 2: load the .NET runtime via pythonnet ---")
    try:
        from pythonnet import load
        # Use the .NET Framework CLR already built into Windows, so nobody
        # needs to separately install a .NET (Core) runtime.
        load("netfx")
        import clr
    except ImportError:
        print("pythonnet isn't installed. Run: pip install pythonnet")
        return
    except Exception as e:
        print(f"Failed to initialize the .NET runtime: {e!r}")
        print("If this mentions a missing runtime, you may need to install the")
        print(".NET Desktop Runtime from https://dotnet.microsoft.com/download")
        return
    print("Runtime loaded.\n")

    print("--- Step 3: load LibreHardwareMonitorLib.dll ---")
    try:
        clr.AddReference(DLL_PATH)
        from LibreHardwareMonitor.Hardware import Computer, HardwareType, SensorType
    except Exception as e:
        print(f"Failed to load the DLL: {e!r}")
        print("This can happen if a companion DLL (e.g. HidSharp.dll) is missing")
        print("from the 'libs' folder - copy the rest of the release zip's DLLs")
        print("in alongside LibreHardwareMonitorLib.dll and try again.")
        return
    print("DLL loaded.\n")

    print("--- Step 4: open the Computer object and read CPU sensors ---")
    try:
        computer = Computer()
        computer.IsCpuEnabled = True
        computer.Open()
    except Exception as e:
        print(f"Failed to open Computer(): {e!r}")
        return

    found_any = False
    try:
        for hardware in computer.Hardware:
            if hardware.HardwareType != HardwareType.Cpu:
                continue
            hardware.Update()
            print(f"CPU: {hardware.Name}")
            for sensor in hardware.Sensors:
                if sensor.SensorType == SensorType.Temperature:
                    found_any = True
                    val = sensor.Value
                    print(f"  {sensor.Name}: {val if val is not None else '(no value)'}")
    finally:
        computer.Close()

    print()
    if found_any:
        print("RESULT: sensors enumerated successfully. If the values above look like")
        print("real temperatures (not blank/0), paste this whole output back and CPU")
        print("temp can be wired into the main app.")
    else:
        print("RESULT: no temperature sensors were found. If you weren't running as")
        print("Administrator, that's almost certainly why - retry elevated. If you")
        print("were already elevated, paste this whole output back.")


if __name__ == "__main__":
    main()
