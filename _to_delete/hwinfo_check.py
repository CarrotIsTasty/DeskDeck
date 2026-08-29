"""
Standalone HWiNFO shared-memory diagnostic.

Run this on its own (stdlib only, no PyQt/pycaw/pynvml needed) to check
whether HWiNFO's Shared Memory feature is exposing sensor data, and to see
exactly what CPU-related temperature readings it's reporting, before this
gets wired into the full Mini Control Center app.

Usage:
    venv\\Scripts\\activate
    python hwinfo_check.py

Before running: in HWiNFO's Sensors window, click the gear/Settings icon and
make sure "Shared Memory Support" is checked. Leave HWiNFO running (tray is
fine) while you run this.
"""

import ctypes
import struct
from ctypes import wintypes

FILE_MAP_READ = 0x0004
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

# HWiNFO tries to create the mapping in the "Global\" namespace (visible to
# all sessions); if that's not accessible it falls back to the local one.
CANDIDATE_NAMES = ["Global\\HWiNFO_SENS_SM2", "HWiNFO_SENS_SM2"]

# --- Reading element layout (HWiNFO_SENSORS_READING_ELEMENT) ---
# tReading(int32) + dwSensorIndex(u32) + dwReadingID(u32)
#   + szLabelOrig[128] + szLabelUser[128] + szUnit[16]
#   + 4 bytes padding (to 8-byte-align the doubles that follow)
#   + Value(double) + ValueMin(double) + ValueMax(double) + ValueAvg(double)
READING_OFF_TREADING = 0
READING_OFF_SENSORIDX = 4
READING_OFF_READINGID = 8
READING_OFF_LABEL_ORIG = 12
READING_OFF_LABEL_USER = 140
READING_OFF_UNIT = 268
READING_OFF_VALUE = 288  # after 4 bytes padding for 8-byte alignment
SENSOR_TYPE_TEMP = 1


def open_mapping():
    for name in CANDIDATE_NAMES:
        handle = kernel32.OpenFileMappingW(FILE_MAP_READ, False, name)
        if handle:
            return name, handle
    return None, None


def main():
    print("Looking for HWiNFO's shared memory object...\n")
    name, handle = open_mapping()
    if not handle:
        err = ctypes.get_last_error()
        print(f"RESULT: NOT FOUND under either name (last error {err}).")
        print("Tried:", ", ".join(CANDIDATE_NAMES))
        print()
        print("Likely causes:")
        print("  1. 'Shared Memory Support' isn't checked in HWiNFO's Sensors")
        print("     window -> gear/Settings icon.")
        print("  2. HWiNFO isn't currently running (check the tray / Task Manager).")
        print("  3. HWiNFO is running elevated while this script isn't (or vice")
        print("     versa) - try running both the same way.")
        return

    print(f'RESULT: FOUND mapping "{name}". Reading header...\n')
    view = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
    if not view:
        print(f"...but MapViewOfFile failed (error {ctypes.get_last_error()}). Please report this.")
        kernel32.CloseHandle(handle)
        return

    try:
        header = ctypes.string_at(view, 44)
        signature, version, revision = struct.unpack_from("<III", header, 0)
        # poll_time (__time64_t) is 8-byte aligned -> starts at offset 16
        off_sensor_sec, sz_sensor_el, n_sensor_el, off_reading_sec, sz_reading_el, n_reading_el = \
            struct.unpack_from("<IIIIII", header, 20)

        print(f"dwSignature = 0x{signature:08X} (expect 0x53695748)")
        print(f"dwVersion = {version}, dwRevision = {revision}")
        print(f"dwOffsetOfReadingSection = {off_reading_sec}")
        print(f"dwSizeOfReadingElement   = {sz_reading_el} (my assumed layout expects 320)")
        print(f"dwNumReadingElements     = {n_reading_el}")
        print()

        if signature != 0x53695748:
            print("Signature doesn't match - HWiNFO's shared memory format may have")
            print("changed. Please paste this whole output back.")
            return

        cpu_temps = []
        for i in range(n_reading_el):
            base = off_reading_sec + i * sz_reading_el
            elem = ctypes.string_at(view + base, min(sz_reading_el, 400))
            t_reading = struct.unpack_from("<i", elem, READING_OFF_TREADING)[0]
            if t_reading != SENSOR_TYPE_TEMP:
                continue
            label = elem[READING_OFF_LABEL_ORIG:READING_OFF_LABEL_ORIG + 128].split(b"\x00", 1)[0].decode("latin-1", "replace")
            if "cpu" not in label.lower():
                continue
            value = struct.unpack_from("<d", elem, READING_OFF_VALUE)[0]
            cpu_temps.append((label, value))

        if not cpu_temps:
            print("Found the sensor table, but no reading had type=TEMP with a label")
            print("containing 'cpu'. Dumping the first 5 TEMP readings of any label")
            print("so we can see what's actually there:")
            shown = 0
            for i in range(n_reading_el):
                if shown >= 5:
                    break
                base = off_reading_sec + i * sz_reading_el
                elem = ctypes.string_at(view + base, min(sz_reading_el, 400))
                t_reading = struct.unpack_from("<i", elem, READING_OFF_TREADING)[0]
                if t_reading != SENSOR_TYPE_TEMP:
                    continue
                label = elem[READING_OFF_LABEL_ORIG:READING_OFF_LABEL_ORIG + 128].split(b"\x00", 1)[0].decode("latin-1", "replace")
                value = struct.unpack_from("<d", elem, READING_OFF_VALUE)[0]
                print(f"  [{i}] label={label!r} value={value}")
                shown += 1
            print()
            print("Please paste this whole output back.")
            return

        print(f"Found {len(cpu_temps)} CPU-labelled temperature reading(s):")
        for label, value in cpu_temps:
            print(f"  {label!r}: {value:.1f}")
        highest = max(v for _, v in cpu_temps)
        print()
        print(f"RESULT: parsing looks correct. Highest CPU-labelled temp = {highest:.1f} C")
        print("If these numbers look sane (double check against HWiNFO's own window),")
        print("paste this output back and CPU temp can be wired into the main app.")
    finally:
        kernel32.UnmapViewOfFile(view)
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    main()
