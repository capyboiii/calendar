"""Drain child output while concurrent workloads run (Windows pipes are small)."""
import subprocess
import threading


def drain_process(process):
    result = []
    thread = threading.Thread(target=lambda: result.append(process.communicate()), daemon=True)
    process._test_output = (thread, result)
    thread.start()


def finish_process(process, timeout):
    thread, result = process._test_output
    thread.join(timeout)
    if thread.is_alive():
        raise subprocess.TimeoutExpired(process.args, timeout)
    return result[0]
