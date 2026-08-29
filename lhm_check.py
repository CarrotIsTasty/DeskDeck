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
        try:
            from pythonnet import load
            load("netfx")
        except Exception:
            pass
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
        dll_dir = os.path.dirname(os.path.abspath(DLL_PATH))
        if dll_dir not in sys.path:
            sys.path.insert(0, dll_dir)
        clr.AddReference(DLL_PATH)
        from LibreHardwareMonitor.Hardware import Computer, HardwareType, SensorType
    except Exception as e:
        print(f"Failed to load the DLL: {e!r}")
        print("This can happen if a companion DLL (e.g. HidSharp.dll) is missing")
        print("from the 'libs' folder - copy the rest of the release zip's DLLs")
        print("in alongside LibreHardwareMonitorLib.dll and try again.")
        return
    print("DLL loaded.\n")

    print("--- Step 4: open Computer object and read all hardware sensors ---")
    try:
        computer = Computer()
        computer.IsCpuEnabled = True
        computer.IsMotherboardEnabled = True
        computer.IsControllerEnabled = True
        computer.Open()
    except Exception as e:
        print(f"Failed to open Computer(): {e!r}")
        return

    found_any = False

    def print_hardware_sensors(hardware, depth=0):
        nonlocal found_any
        indent = "  " * depth
        hardware.Update()
        print(f"{indent}[{hardware.HardwareType}] {hardware.Name}")
        for sensor in hardware.Sensors:
            if sensor.SensorType == SensorType.Temperature:
                val = sensor.Value
                if val is not None:
                    found_any = True
                print(f"{indent}  * Temp: {sensor.Name} = {val if val is not None else '(null/empty)'}")
        if hasattr(hardware, "SubHardware"):
            for sub in hardware.SubHardware:
                print_hardware_sensors(sub, depth + 1)

    try:
        for hardware in computer.Hardware:
            print_hardware_sensors(hardware)
    finally:
        computer.Close()

    print()
    if found_any:
        print("RESULT: Sensor values read successfully!")
    else:
        print("RESULT: Temperature sensor objects exist, but their values are (null/empty).")
        print("Reasons:")
        print("1. Process is not elevated (Run as administrator).")
        print("2. Windows 11 'Microsoft Vulnerable Driver Blocklist' / Core Isolation is blocking WinRing0x64.sys.")



if __name__ == "__main__":
    main()
