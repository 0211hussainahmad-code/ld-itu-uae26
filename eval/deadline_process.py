"""Bound a git command and its descendants, including inherited output pipes.

Windows uses a kill-on-close Job Object. A stdin-gated worker is attached before it
receives the command, so the command cannot spawn descendants outside the job in a
process-creation race. Failure to establish that containment fails closed.
"""
import json
import base64
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


class WindowsJob:
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w

        class BasicLimits(c.Structure):
            _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong), ("flags", w.DWORD),
                        ("min_ws", c.c_size_t), ("max_ws", c.c_size_t), ("active", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class IO(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops",
                                                         "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(c.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IO), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]

        self.c = c
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.kernel.SetInformationJobObject.restype = w.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = w.BOOL
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.PeekNamedPipe.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.c_void_p,
                                             c.POINTER(w.DWORD), c.c_void_p]
        self.kernel.PeekNamedPipe.restype = w.BOOL
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway permission
        if not self.kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def worker_pid(self, process, deadline):
        """Read the actual interpreter PID, not a Windows venv redirector's PID.

        Peek before reading so a stalled startup cannot block this handshake. No command
        has been sent yet; this worker can only identify itself and wait for stdin.
        """
        import msvcrt
        from ctypes import wintypes as w
        pipe = msvcrt.get_osfhandle(process.stdout.fileno())
        data = b""
        while time.monotonic() < deadline:
            available = w.DWORD()
            if not self.kernel.PeekNamedPipe(pipe, None, 0, None, self.c.byref(available), None):
                raise self.c.WinError(self.c.get_last_error())
            if available.value:
                data += os.read(process.stdout.fileno(), min(available.value, 64))
                if b"\n" in data:
                    return int(data.strip())
                if len(data) > 64:
                    raise OSError("invalid bounded-worker PID handshake")
            else:
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        raise subprocess.TimeoutExpired(process.args, 0)

    def assign_pid(self, pid):
        process_handle = self.kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not process_handle:
            raise self.c.WinError(self.c.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process_handle):
                raise self.c.WinError(self.c.get_last_error())
        finally:
            self.kernel.CloseHandle(process_handle)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run(args, *, capture_output=True, text=False, timeout=30.0, input=None):
    if not math.isfinite(timeout) or timeout <= 0:
        raise subprocess.TimeoutExpired(args, timeout)
    started = time.monotonic()
    cleanup = min(5.0, timeout / 4)
    job = WindowsJob() if os.name == "nt" else None
    process = None
    released = False
    try:
        options = ({"creationflags": subprocess.CREATE_NO_WINDOW, "stdin": subprocess.PIPE}
                   if job else {"start_new_session": True})
        if input is not None:
            options["stdin"] = subprocess.PIPE
        if text:
            options.update(encoding="utf-8", errors="replace")
        command = [sys.executable, str(Path(__file__).resolve()), "--worker"] if job else args
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, **options)
        payload = input
        try:
            if job:
                pid = job.worker_pid(process, started + timeout - cleanup)
                job.assign_pid(pid)
                forwarded = input.encode("utf-8") if isinstance(input, str) else input
                payload = json.dumps({"args": args, "input": base64.b64encode(forwarded).decode("ascii")
                                      if forwarded is not None else None}) + "\n"
                if not text:
                    payload = payload.encode("ascii")
            released = True
            stdout, stderr = process.communicate(input=payload,
                timeout=max(0.001, timeout - cleanup - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            if job:
                job.close()  # atomically terminates the gated worker and every descendant
                if not released:
                    process.stdin.close()  # an unattached worker sees EOF, never a command
                if process.poll() is None:
                    process.kill()  # also reap a venv redirector outside the job
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            stdout, stderr = None, None
            try:
                stdout, stderr = process.communicate(timeout=max(0.001, timeout - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                process.kill()
                # Never synchronously close a buffered pipe held by a Windows reader thread.
            raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr) from None
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    finally:
        if job:
            job.close()
            if not released and process is not None and process.stdin:
                process.stdin.close()
        if process is not None and process.poll() is None:
            process.kill()


if __name__ == "__main__":
    print(os.getpid(), flush=True)
    line = sys.stdin.buffer.readline()
    if not line:
        raise SystemExit(2)
    request = json.loads(line)
    forwarded = base64.b64decode(request["input"]) if request.get("input") is not None else None
    raise SystemExit(subprocess.run(request["args"], input=forwarded).returncode)
