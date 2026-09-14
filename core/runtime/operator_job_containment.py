#!/usr/bin/env python3
"""Optional Windows Job Object containment for operator child processes.

When available, assigning children to a job with KILL_ON_JOB_CLOSE means that if
the controlling process exits abruptly (e.g. Cursor UI Stop), the OS can tear
down the job's children. This does not hook Cursor itself — it is defensive
containment for processes we spawn.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any


class JobContainmentUnavailable(RuntimeError):
    pass


class WindowsJobContainment:
    """Create a Windows Job Object and assign child PIDs to it."""

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    def __init__(self, name: str | None = None):
        if sys.platform != "win32":
            raise JobContainmentUnavailable("Windows only")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle = self._kernel32.CreateJobObjectW(None, name)
        if not self._handle:
            raise JobContainmentUnavailable(f"CreateJobObject failed: {ctypes.get_last_error()}")
        self._configure_kill_on_close()

    def _configure_kill_on_close(self) -> None:
        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._kernel32.SetInformationJobObject(
            self._handle,
            self.JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            raise JobContainmentUnavailable(
                f"SetInformationJobObject failed: {ctypes.get_last_error()}"
            )

    def assign_pid(self, pid: int) -> bool:
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        PROCESS_ALL = PROCESS_SET_QUOTA | PROCESS_TERMINATE | 0x0400  # QUERY_INFORMATION
        handle = self._kernel32.OpenProcess(PROCESS_ALL, False, int(pid))
        if not handle:
            return False
        try:
            ok = self._kernel32.AssignProcessToJobObject(self._handle, handle)
            return bool(ok)
        finally:
            self._kernel32.CloseHandle(handle)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "WindowsJobContainment":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def try_create_job(name: str | None = None) -> WindowsJobContainment | None:
    try:
        return WindowsJobContainment(name=name)
    except JobContainmentUnavailable:
        return None
    except Exception:
        return None
