from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import wx

from app import DemoFrame
from tts_backend import AUDITION_LANGUAGES, LANGUAGE_NAMES, MODELS, Result


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self) -> None:
        self.frame = DemoFrame()
        self.frame.Show()
        wx.Yield()

    def tearDown(self) -> None:
        self.frame.timer.Stop()
        self.frame._stop()
        self.frame.Destroy()
        wx.Yield()

    def test_all_model_and_language_controls(self) -> None:
        for index, model in enumerate(MODELS):
            with self.subTest(model=model.key):
                self.frame.model_choice.SetSelection(index)
                self.frame._select_model()
                self.assertEqual(self.frame.sid.GetValue(), model.default_sid)
                self.assertEqual(self.frame.language.GetCount(), len(model.languages))
                self.assertEqual(self.frame.reference.IsEnabled(), model.family in ("zipvoice", "pocket"))
                for language_index, language in enumerate(model.languages):
                    self.frame.language.SetSelection(language_index)
                    self.frame._select_language()
                    if self.frame.preset.GetCount():
                        self.assertTrue(self.frame.text.GetValue())

    def test_background_job_returns_on_ui_thread(self) -> None:
        finished = []
        main_thread = threading.get_ident()

        def work() -> int:
            time.sleep(0.1)
            return 42

        self.frame._run(work, lambda value: finished.append((value, threading.get_ident())))
        self.assertTrue(self.frame.busy)
        self.assertFalse(self.frame.model_choice.IsEnabled())
        deadline = time.monotonic() + 3
        while not finished and time.monotonic() < deadline:
            wx.Yield()
            time.sleep(0.01)
        self.assertEqual(finished, [(42, main_thread)])
        self.assertFalse(self.frame.busy)
        self.assertTrue(self.frame.model_choice.IsEnabled())

    def test_audio_history_and_clip_playback(self) -> None:
        if not self.frame.results:
            self.skipTest("Generate audition audio with verify_models.py first.")
        self.frame.history.SetSelection(0)
        self.frame._select_result()
        self.assertIsNotNone(self.frame.current)
        self.frame.clip_start.SetValue(0)
        self.frame.clip_duration.SetValue(0.5)
        with patch("app.sd.play") as play:
            self.frame._play_clip(wx.CommandEvent())
            play.assert_called_once()
            samples, rate = play.call_args.args
            self.assertEqual(len(samples), int(0.5 * rate))
            self.assertTrue(self.frame.playing)
        self.frame._stop()
        self.assertFalse(self.frame.playing)

    def test_batch_generates_twenty_labelled_results(self) -> None:
        self._check_batch(stop_after=None)

    def test_batch_cancellation_keeps_completed_results(self) -> None:
        self._check_batch(stop_after=3)

    def _check_batch(self, stop_after: int | None) -> None:
        initial = len(self.frame.results)
        calls = []

        def synthesize(request, progress, cancel):
            calls.append(request.language)
            if len(calls) == stop_after:
                cancel.set()
            return Result(Path("test.wav"), np.full(100, 0.1, dtype=np.float32), 100, 0.1, 0, request)

        with (
            patch.object(self.frame.engine.store, "ready", return_value=True),
            patch.object(self.frame.engine, "synthesize", side_effect=synthesize),
        ):
            self.frame._generate_twenty(wx.CommandEvent())
            self.assertFalse(self.frame.batch_button.IsEnabled())
            deadline = time.monotonic() + 5
            while self.frame.busy and time.monotonic() < deadline:
                wx.Yield()
                time.sleep(0.01)
        expected = stop_after or 20
        self.assertFalse(self.frame.busy)
        self.assertTrue(self.frame.batch_button.IsEnabled())
        self.assertEqual(len(self.frame.results) - initial, expected)
        self.assertEqual(tuple(calls), AUDITION_LANGUAGES[:expected])
        self.assertIn(f"{expected}/20", self.frame.status.GetLabel())
        for index, language in enumerate(calls, initial):
            self.assertIn(LANGUAGE_NAMES[language], self.frame.history.GetString(index))


if __name__ == "__main__":
    unittest.main()
