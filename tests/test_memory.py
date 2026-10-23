from __future__ import annotations

import io
import os
import queue
import sys
import unittest
from dataclasses import asdict

from benchmark_memory import MIB, Memory, Phase, WindowsMemory, read_lines, summarize


class MemoryBenchmarkTests(unittest.TestCase):
    def test_phase_tracks_peak_and_last_separately(self) -> None:
        phase = Phase()
        phase.add(Memory(100, 200, 150, 250))
        phase.add(Memory(80, 220, 150, 250))
        self.assertEqual(phase.samples, 2)
        self.assertEqual(phase.peak_rss, 100)
        self.assertEqual(phase.last_rss, 80)
        self.assertEqual(phase.peak_private, 220)
        self.assertEqual(phase.last_private, 220)

    def test_summary_median_and_max_are_not_confused(self) -> None:
        rows = []
        for size in (10, 20, 90):
            phase = asdict(Phase(3, size * MIB, 2 * size * MIB, size * MIB, 2 * size * MIB))
            rows.append({
                "model": "test", "title": "Test", "language": "en", "ok": True,
                "phases": {name: phase for name in ("baseline", "loading", "cold_synthesis", "warm_synthesis")},
                "process_peak_rss_bytes": size * MIB, "process_peak_commit_bytes": 2 * size * MIB,
                "runs": {name: {"synthesis_seconds": 1, "duration_seconds": 5} for name in ("cold", "warm")},
            })
        rows.append({"model": "test", "ok": False})
        result = summarize(rows)[0]
        self.assertEqual(result["trials"], 3)
        self.assertEqual(result["process_peak_rss_mib"], 20)
        self.assertEqual(result["process_peak_rss_max_mib"], 90)
        self.assertEqual(result["cold_peak_private_mib"], 40)

    def test_failed_models_are_not_success_shaped(self) -> None:
        self.assertEqual(summarize([{"model": "failed", "ok": False}]), [])

    def test_stream_reader_signals_end_of_file(self) -> None:
        events: queue.Queue[str | None] = queue.Queue()
        read_lines(io.StringIO("one\ntwo\n"), events)
        self.assertEqual([events.get_nowait() for _ in range(3)], ["one\n", "two\n", None])

    @unittest.skipUnless(sys.platform == "win32", "Windows process-memory counters")
    def test_native_counters_detect_committed_and_resident_allocation(self) -> None:
        probe = WindowsMemory(os.getpid())
        try:
            before = probe.read()
            allocation = bytearray(16 * MIB)
            for index in range(0, len(allocation), 4096):
                allocation[index] = 1
            after = probe.read()
            self.assertGreater(after.private - before.private, 8 * MIB)
            self.assertGreater(after.rss - before.rss, 8 * MIB)
            self.assertGreaterEqual(after.peak_rss, after.rss)
            self.assertGreaterEqual(after.peak_commit, after.private)
        finally:
            probe.close()


if __name__ == "__main__":
    unittest.main()
