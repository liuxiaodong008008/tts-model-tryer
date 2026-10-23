from __future__ import annotations

import argparse
import csv
import ctypes
import importlib.metadata
import io
import json
import os
import platform
import queue
import statistics
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parent
MIB = 1024 * 1024
PREFIX = "MEMORY_BENCH:"


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


@dataclass(frozen=True)
class Memory:
    rss: int
    private: int
    peak_rss: int
    peak_commit: int


class WindowsMemory:
    def __init__(self, pid: int):
        if sys.platform != "win32":
            raise OSError("This benchmark requires the Windows process-memory API.")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD,
        ]
        self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self) -> Memory:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not self.psapi.GetProcessMemoryInfo(self.handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return Memory(
            counters.WorkingSetSize, counters.PrivateUsage,
            counters.PeakWorkingSetSize, counters.PeakPagefileUsage,
        )

    def close(self) -> None:
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


@dataclass
class Phase:
    samples: int = 0
    peak_rss: int = 0
    peak_private: int = 0
    last_rss: int = 0
    last_private: int = 0

    def add(self, memory: Memory) -> None:
        self.samples += 1
        self.peak_rss = max(self.peak_rss, memory.rss)
        self.peak_private = max(self.peak_private, memory.private)
        self.last_rss = memory.rss
        self.last_private = memory.private


def emit(event: dict[str, object]) -> None:
    print(PREFIX + json.dumps(event, ensure_ascii=False), flush=True)
    if sys.stdin.readline().strip() != "continue":
        raise RuntimeError("Benchmark controller disconnected.")


def worker(key: str, threads: int, output: Path) -> None:
    import numpy as np
    from unittest.mock import patch

    from tts_backend import MODEL_BY_KEY, PRESETS, Engine, Request

    model = MODEL_BY_KEY[key]
    language = model.languages[0]
    request = Request(
        key, PRESETS[language][0][1], language, sid=model.default_sid,
        threads=threads, steps=8 if key == "supertonic" else 5,
    )
    engine = Engine(output=output)
    emit({
        "event": "phase", "name": "baseline", "pid": os.getpid(),
        "model": key, "title": model.title, "language": language, "text": request.text,
    })
    for run in ("cold", "warm"):
        if run == "warm":
            emit({"event": "phase", "name": "warm_prepare"})

        def observe(stage: str) -> None:
            names = {
                "load_start": "loading", "load_end": "loaded",
                "synthesis_start": f"{run}_synthesis", "synthesis_end": f"{run}_finished",
            }
            emit({"event": "phase", "name": names[stage]})

        with patch("urllib.request.urlopen", side_effect=AssertionError("Benchmark must stay offline")):
            result = engine.synthesize(request, lambda *args: None, threading.Event(), observe=observe)
        rms = float(np.sqrt(np.mean(result.samples ** 2)))
        if result.duration < 0.2 or rms < 1e-4:
            raise ValueError("Generated audio is too short or effectively silent.")
        emit({
            "event": "result", "run": run, "duration_seconds": result.duration,
            "synthesis_seconds": result.elapsed, "load_seconds": result.load_seconds,
            "rtf": result.rtf, "rms": rms, "audio_path": str(result.path),
        })
        del result
    emit({"event": "complete"})


def read_lines(stream: TextIO, events: queue.Queue[str | None]) -> None:
    try:
        for line in stream:
            events.put(line)
    finally:
        events.put(None)


def measure(key: str, trial: int, threads: int, interval: float, output: Path) -> dict:
    log_path = output / f"{key}-trial-{trial}.log"
    environment = dict(os.environ, PYTHONUTF8="1")
    command = [
        sys.executable, str(Path(__file__).resolve()), "--worker", key,
        "--threads", str(threads), "--output", str(output),
    ]
    phases: dict[str, Phase] = {}
    results = {}
    info = {}
    peak_rss = peak_commit = 0
    phase = ""
    probe: WindowsMemory | None = None
    complete = False
    events: queue.Queue[str | None] = queue.Queue()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding="utf-8", env=environment,
        )
        if process.stdout is None or process.stdin is None:
            raise RuntimeError("Unable to open benchmark process pipes.")
        reader = threading.Thread(target=read_lines, args=(process.stdout, events), daemon=True)
        reader.start()

        def sample() -> None:
            nonlocal peak_rss, peak_commit
            if probe is not None:
                memory = probe.read()
                phases.setdefault(phase, Phase()).add(memory)
                peak_rss = max(peak_rss, memory.peak_rss)
                peak_commit = max(peak_commit, memory.peak_commit)

        deadline = time.monotonic() + 300
        try:
            while not complete:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{key} exceeded the 300 second trial limit.")
                sample()
                try:
                    line = events.get(timeout=interval)
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError(f"{key} exited before completing; see {log_path}.")
                if not line.startswith(PREFIX):
                    raise RuntimeError(f"Unexpected worker output: {line.strip()}")
                event = json.loads(line[len(PREFIX):])
                sample()
                if event["event"] == "phase":
                    if event["name"] == "baseline":
                        info = {name: event[name] for name in ("model", "title", "language", "text", "pid")}
                        probe = WindowsMemory(event["pid"])
                    phase = event["name"]
                    sample()
                elif event["event"] == "result":
                    results[event["run"]] = event
                elif event["event"] == "complete":
                    complete = True
                else:
                    raise ValueError(f"Unknown benchmark event: {event['event']}")
                process.stdin.write("continue\n")
                process.stdin.flush()
            process.wait(timeout=15)
            if process.returncode != 0:
                raise RuntimeError(f"{key} exited with {process.returncode}; see {log_path}.")
        finally:
            if probe is not None:
                probe.close()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()
            reader.join(timeout=2)
    required_phases = {"baseline", "loading", "loaded", "cold_synthesis", "warm_synthesis"}
    if not required_phases <= phases.keys() or set(results) != {"cold", "warm"}:
        raise ValueError(f"Incomplete measurement for {key}.")
    return {
        **info, "trial": trial, "ok": True, "phases": {name: asdict(stats) for name, stats in phases.items()},
        "process_peak_rss_bytes": peak_rss, "process_peak_commit_bytes": peak_commit,
        "runs": results, "log": str(log_path),
    }


def summarize(trials: list[dict]) -> list[dict]:
    summary = []
    for key in dict.fromkeys(row["model"] for row in trials):
        rows = [row for row in trials if row["model"] == key and row["ok"]]
        if not rows:
            continue

        def median_phase(phase: str, field: str) -> float:
            return statistics.median(row["phases"][phase][field] for row in rows) / MIB

        summary.append({
            "model": key, "title": rows[0]["title"], "language": rows[0]["language"], "trials": len(rows),
            "baseline_rss_mib": median_phase("baseline", "last_rss"),
            "load_peak_rss_mib": median_phase("loading", "peak_rss"),
            "cold_peak_rss_mib": median_phase("cold_synthesis", "peak_rss"),
            "warm_peak_rss_mib": median_phase("warm_synthesis", "peak_rss"),
            "cold_peak_private_mib": median_phase("cold_synthesis", "peak_private"),
            "warm_peak_private_mib": median_phase("warm_synthesis", "peak_private"),
            "process_peak_rss_mib": statistics.median(row["process_peak_rss_bytes"] for row in rows) / MIB,
            "process_peak_rss_max_mib": max(row["process_peak_rss_bytes"] for row in rows) / MIB,
            "process_peak_commit_mib": statistics.median(row["process_peak_commit_bytes"] for row in rows) / MIB,
            "cold_seconds": statistics.median(row["runs"]["cold"]["synthesis_seconds"] for row in rows),
            "warm_seconds": statistics.median(row["runs"]["warm"]["synthesis_seconds"] for row in rows),
            "audio_seconds": statistics.median(row["runs"]["cold"]["duration_seconds"] for row in rows),
        })
    return summary


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Benchmark native Windows memory for every local TTS model.")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--interval-ms", type=int, default=20)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "memory-benchmark")
    args = parser.parse_args()
    if args.repeats < 1 or not 1 <= args.threads <= 16 or not 1 <= args.interval_ms <= 1000:
        parser.error("repeats >= 1, threads 1..16 and interval-ms 1..1000 are required.")
    from tts_backend import MODEL_BY_KEY, ModelStore

    if args.worker:
        worker(args.worker, args.threads, args.output / "audio")
        return
    if sys.platform != "win32":
        parser.error("This benchmark uses Windows GetProcessMemoryInfo.")
    keys = args.models if args.models is not None else list(MODEL_BY_KEY)
    if not keys or any(key not in MODEL_BY_KEY for key in keys):
        parser.error(f"Choose models from: {', '.join(MODEL_BY_KEY)}")
    missing = [key for key in keys if not ModelStore().ready(MODEL_BY_KEY[key])]
    if missing:
        parser.error(f"Local model packages missing: {', '.join(missing)}")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "environment": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "platform": platform.platform(), "python": sys.version,
            "processor": platform.processor(), "logical_cpu_count": os.cpu_count(),
            "sherpa_onnx": importlib.metadata.version("sherpa-onnx"),
            "numpy": importlib.metadata.version("numpy"),
        },
        "method": {
            "repeats": args.repeats, "threads": args.threads, "sampling_interval_ms": args.interval_ms,
            "isolation": "New process per trial; same process/model reused for its second synthesis.",
            "rss": "Windows WorkingSetSize; phase peaks sampled externally. Process peak uses PeakWorkingSetSize.",
            "private": "PrivateUsage and OS lifetime PeakPagefileUsage (commit), not Python heap or GPU memory.",
            "phase_boundaries": "Worker handshakes at load/generate boundaries; sampler uses the worker's actual PID.",
            "baseline": "After Python/runtime imports, before model loading; GUI and benchmark controller excluded.",
            "input": "Default Chinese preset where supported, otherwise English; one cold and one warm synthesis.",
            "summary": "Median of successful trials; process_peak_rss_max_mib is the maximum across trials.",
        },
        "trials": [], "summary": [],
    }
    path = args.output / "results.json"
    for key in keys:
        for trial in range(1, args.repeats + 1):
            print(f"MEASURE {key} {trial}/{args.repeats}", flush=True)
            try:
                result = measure(key, trial, args.threads, args.interval_ms / 1000, args.output)
                report["trials"].append(result)
                print(f"PASS {key}: OS peak RSS {result['process_peak_rss_bytes'] / MIB:.1f} MiB", flush=True)
            except Exception as error:
                traceback.print_exc()
                report["trials"].append({"model": key, "trial": trial, "ok": False, "error": str(error)})
                print(f"FAIL {key}: {error}", flush=True)
            report["summary"] = summarize(report["trials"])
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["summary"]:
        with (args.output / "summary.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(report["summary"][0]))
            writer.writeheader()
            writer.writerows(report["summary"])
    if any(not trial["ok"] for trial in report["trials"]):
        raise SystemExit(f"Some trials failed. See {path}.")
    print(f"ALL {len(report['trials'])} MEMORY TRIALS PASSED: {path}", flush=True)


if __name__ == "__main__":
    main()
