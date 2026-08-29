"""
Standalone Core Temp shared-memory diagnostic.

Run this on its own (no PyQt/pycaw/pynvml needed) to check, independently of
the full Mini Control Center app, whether Core Temp's Shared Memory feature
is actually exposing data on this machine.

Usage:
    venv\\Scripts\\activate
    python core_temp_check.py

(or just: python core_temp_check.py, using any Python 3 - it only needs the
standard library.)
"""

import ctypes
from ctypes import wintypes

MAPPING_NAME = "CoreTempMappingObject"
FILE_MAP_READ = 0x0004

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def main():
    print(f'Looking for shared memory object named "{MAPPING_NAME}"...\n')

    handle = kernel32.OpenFileMappingW(FILE_MAP_READ, False, MAPPING_NAME)
    if not handle:
        err = ctypes.get_last_error()
        print(f"RESULT: NOT FOUND (OpenFileMappingW failed, Windows error code {err}).")
        print()
        if err == 2:
            print("Error 2 = ERROR_FILE_NOT_FOUND. This means Windows has no object by that")
            print("name right now. Most likely causes, in order of likelihood:")
        print("  1. Core Temp's 'Shared Memory' setting isn't turned on.")
        print("     Open Core Temp -> Options menu -> Settings... and look for a")
        print("     checkbox called 'Shared Memory' (sometimes under a tab like")
        print("     'Interface' or 'General', and sometimes labelled 'Enable Core")
        print("     Temp Shared Memory'). Enable it, click OK, and re-run this script.")
        print("  2. Core Temp isn't actually running (check the system tray / Task")
        print("     Manager for 'Core Temp.exe' or 'CoreTemp.exe').")
        print("  3. Core Temp is running elevated (as Administrator) while this script")
        print("     runs un-elevated, or vice versa - named objects created by an")
        print("     elevated process aren't visible to a non-elevated one by default.")
        print("     Try running both Core Temp and this script the same way (both")
        print("     normal, or both 'Run as administrator').")
        return

    print("RESULT: FOUND the shared memory object. Reading it now...\n")

    view = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
    if not view:
        print(f"...but MapViewOfFile failed (error {ctypes.get_last_error()}). Unexpected -")
        print("please report this back with the error code.")
        kernel32.CloseHandle(handle)
        return

    try:
        # Read enough bytes to cover uiLoad[256] + uiTjMax[128] + uiCoreCnt + uiCPUCnt
        # + fTemp[256] + a little extra, without assuming the full struct size -
        # this works even if a newer/older Core Temp version changed trailing fields.
        header_size = (256 + 128) * 4 + 4 + 4 + (256 * 4) + 32
        raw = ctypes.string_at(view, header_size)

        import struct
        core_cnt = struct.unpack_from("<I", raw, 256 * 4 + 128 * 4)[0]
        cpu_cnt = struct.unpack_from("<I", raw, 256 * 4 + 128 * 4 + 4)[0]
        temps_offset = 256 * 4 + 128 * 4 + 4 + 4
        print(f"uiCoreCnt = {core_cnt}")
        print(f"uiCPUCnt  = {cpu_cnt}")

        if 0 < core_cnt <= 256:
            temps = struct.unpack_from(f"<{core_cnt}f", raw, temps_offset)
            print(f"Per-core temps (raw floats) = {[round(t, 1) for t in temps]}")
            print()
            print(f"RESULT: Shared memory is working. Highest core temp = {round(max(temps))} C")
            print("If Mini Control Center still shows N/A, restart it (or wait ~1s for the")
            print("next poll) and it should now pick this up.")
        else:
            print()
            print(f"uiCoreCnt looks implausible ({core_cnt}) - the struct layout this script")
            print("assumes may not match your Core Temp version. Please paste this entire")
            print("output back so the struct definition can be corrected.")
    finally:
        kernel32.UnmapViewOfFile(view)
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    main()
