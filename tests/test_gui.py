from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import wx

from app import DemoFrame
from i18n import ENGLISH
from tts_backend import AUDITION_LANGUAGES, MODELS, Request, Result


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self) -> None:
        self.config_directory = tempfile.TemporaryDirectory()
        self.config_path = Path(self.config_directory.name) / "settings.ini"
        self.config = wx.FileConfig(localFilename=str(self.config_path))
        self.frame = DemoFrame(config=self.config)
        self.frame.Show()
        wx.Yield()

    def tearDown(self) -> None:
        self.frame.timer.Stop()
        self.frame._stop()
        self.frame.Destroy()
        wx.Yield()
        self.config.Flush()
        self.config_directory.cleanup()

    def test_all_model_and_language_controls(self) -> None:
        for locale in ("zh", "en"):
            self.frame._set_ui_language(locale, persist=False)
            for index, model in enumerate(MODELS):
                with self.subTest(locale=locale, model=model.key):
                    self.frame.model_choice.SetSelection(index)
                    self.frame._select_model()
                    self.assertEqual(self.frame.sid.GetValue(), model.default_sid)
                    self.assertEqual(self.frame.language.GetCount(), len(model.languages))
                    self.assertEqual(self.frame.reference.IsEnabled(), model.family in ("zipvoice", "pocket"))
                    for language_index, language in enumerate(model.languages):
                        self.frame.language.SetSelection(language_index)
                        self.frame._select_language()
                        self.assertIn(self.frame._name(language), self.frame.language.GetStringSelection())
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
        for locale in ("zh", "en"):
            with self.subTest(locale=locale):
                self.frame._set_ui_language(locale, persist=False)
                self._check_batch(stop_after=None)

    def test_batch_cancellation_keeps_completed_results(self) -> None:
        self._check_batch(stop_after=3)

    def test_switching_languages_preserves_inputs_results_and_playback(self) -> None:
        self.frame.model_choice.SetSelection(2)
        self.frame._select_model()
        self.frame.language.SetSelection(1)
        self.frame._select_language()
        self.frame.preset.SetSelection(2)
        self.frame.text.SetValue("Keep my edited input.")
        self.frame.reference.SetPath(str(Path(self.config_directory.name) / "custom.wav"))
        self.frame.reference_text.SetValue("My reference transcript.")
        self.frame.speed.SetValue(1.3)
        self.frame.threads.SetValue(3)
        self.frame.steps.SetValue(7)
        result = Result(
            Path("test.wav"), np.full(100, 0.1, dtype=np.float32), 100, 0.1, 0,
            Request("kitten", "Hello.", "en"),
        )
        self.frame._append_result(result)
        selected = len(self.frame.results) - 1
        self.frame.history.SetSelection(selected)
        self.frame._select_result()
        self.frame.clip_start.SetValue(0.25)
        self.frame.clip_duration.SetValue(0.5)
        with patch("app.sd.play"), patch("app.sd.stop") as stop:
            self.frame._play_full()
            stop.reset_mock()
            self.frame._set_ui_language("en", persist=False)
            stop.assert_not_called()
        self.assertTrue(self.frame.playing)
        self.assertIs(self.frame.current, result)
        self.assertEqual(self.frame.history.GetSelection(), selected)
        self.assertIn("English (en)", self.frame.history.GetString(selected))
        self.assertIn("Speaker", self.frame.history.GetString(selected))
        self.assertEqual(self.frame.text.GetValue(), "Keep my edited input.")
        self.assertEqual(self.frame.reference_text.GetValue(), "My reference transcript.")
        self.assertTrue(self.frame.reference.GetPath().endswith("custom.wav"))
        self.assertEqual(self.frame.model.key, "zipvoice")
        self.assertEqual(self.frame.language.GetSelection(), 1)
        self.assertEqual(self.frame.preset.GetSelection(), 2)
        self.assertAlmostEqual(self.frame.speed.GetValue(), 1.3)
        self.assertEqual(self.frame.threads.GetValue(), 3)
        self.assertEqual(self.frame.steps.GetValue(), 7)
        self.assertAlmostEqual(self.frame.clip_start.GetValue(), 0.25)
        self.assertAlmostEqual(self.frame.clip_duration.GetValue(), 0.5)
        for control, message in self.frame._labels:
            self.assertEqual(control.GetLabel(), ENGLISH[message])
        self.frame._set_ui_language("zh", persist=False)
        self.assertEqual(self.frame.generate_button.GetLabel(), "合成并试听")
        self.assertEqual(self.frame.text.GetValue(), "Keep my edited input.")

    def test_interface_language_persists_and_restores(self) -> None:
        self.frame._set_ui_language("en")
        restored = wx.FileConfig(localFilename=str(self.config_path))
        other = DemoFrame(config=restored)
        try:
            self.assertEqual(other.ui_locale, "en")
            self.assertEqual(other.generate_button.GetLabel(), "Synthesize and play")
            self.assertIn("Local TTS", other.GetTitle())
        finally:
            other.timer.Stop()
            other.Destroy()
            wx.Yield()

    def test_failed_preference_save_is_reported(self) -> None:
        with patch.object(self.config, "Write", return_value=False), patch("app.wx.MessageBox") as message:
            with self.assertLogs(level="ERROR"):
                self.frame._set_ui_language("en")
        self.assertEqual(message.call_args.args[1], "Could not save settings")
        self.assertIn("Could not save", self.frame.status.GetLabel())

    def test_live_progress_status_and_errors_are_translated(self) -> None:
        self.frame.batch_mode = True
        self.frame._set_busy(True)
        self.frame._show_progress("加载模型", 0, 0, (3, "ja"))
        self.frame._set_ui_language("en", persist=False)
        self.assertEqual(self.frame.status.GetLabel(), "[3/20] Japanese: Loading model")
        self.assertEqual(self.frame.cancel_button.GetLabel(), "Stop batch")
        self.assertFalse(self.frame.generate_button.IsEnabled())
        self.frame._set_busy(False)
        self.frame._set_status("失败：{error}", error="音色 ID 应为 0–7。")
        self.assertEqual(self.frame.status.GetLabel(), "Failed: Speaker ID must be between 0 and 7.")
        self.frame._set_ui_language("zh", persist=False)
        self.assertIn("音色 ID 应为 0–7。", self.frame.status.GetLabel())
        self.frame._set_ui_language("en", persist=False)
        self.frame._cancelled("下载已取消。")
        self.assertEqual(self.frame.status.GetLabel(), "Download cancelled.")

    def test_reference_picker_opens_one_localized_dialog(self) -> None:
        self.frame._set_ui_language("en", persist=False)
        with patch("app.wx.FileDialog") as dialog:
            dialog.return_value.__enter__.return_value.ShowModal.return_value = wx.ID_CANCEL
            button = self.frame.reference.GetPickerCtrl()
            event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
            event.SetEventObject(button)
            button.GetEventHandler().ProcessEvent(event)
            dialog.assert_called_once()
            self.assertEqual(dialog.call_args.args[1], "Choose reference audio")

    def test_validation_dialog_uses_interface_language(self) -> None:
        self.frame._set_ui_language("en", persist=False)
        self.frame.text.SetValue("")
        with patch("app.wx.MessageBox") as message:
            self.frame._generate(wx.CommandEvent())
        self.assertEqual(message.call_args.args[:2], ("Enter text to synthesize.", "Check input"))

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
            self.assertIn(self.frame._name(language), self.frame.history.GetString(index))


if __name__ == "__main__":
    unittest.main()
