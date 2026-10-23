from __future__ import annotations

import ast
import string
import unittest

from i18n import ENGLISH, diagnostic, translate
from tts_backend import LANGUAGE_NAMES, MODELS, ROOT


class TranslationTests(unittest.TestCase):
    def test_format_placeholders_match_in_both_languages(self) -> None:
        formatter = string.Formatter()
        for chinese, english in ENGLISH.items():
            with self.subTest(message=chinese):
                left = {(field, spec) for _, field, spec, _ in formatter.parse(chinese) if field is not None}
                right = {(field, spec) for _, field, spec, _ in formatter.parse(english) if field is not None}
                self.assertEqual(left, right)
                self.assertTrue(english)

    def test_models_and_language_names_have_english_translations(self) -> None:
        for model in MODELS:
            self.assertIn(model.title, ENGLISH)
            self.assertIn(model.description, ENGLISH)
        for name in LANGUAGE_NAMES.values():
            self.assertIn(name, ENGLISH)

    def test_ui_literal_translation_keys_exist(self) -> None:
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            index = 1 if call.func.attr == "_label" else 0
            if call.func.attr not in ("_t", "_label", "_set_status") or len(call.args) <= index:
                continue
            argument = call.args[index]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                self.assertIn(argument.value, ENGLISH)

    def test_owned_backend_error_literals_are_translated(self) -> None:
        tree = ast.parse((ROOT / "tts_backend.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                argument = node.exc.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    self.assertIn(argument.value, ENGLISH)

    def test_formatted_and_external_diagnostics(self) -> None:
        self.assertEqual(diagnostic("en", "参考音频不存在：C:\\audio.wav"), "Reference audio does not exist: C:\\audio.wav")
        self.assertEqual(diagnostic("en", "clip.tar.bz2 大小不符：应为 20，实际 10。请重试下载。"),
                         "clip.tar.bz2 has the wrong size: expected 20, received 10. Download it again.")
        self.assertEqual(diagnostic("en", "PortAudio device error"), "PortAudio device error")
        self.assertEqual(translate("en", "合成完成，已保存：{name}", name="demo.wav"),
                         "Synthesis complete; saved: demo.wav")
        self.assertEqual(translate("en", "{message}", message="Saved"), "Saved")
        with self.assertRaises(ValueError):
            translate("fr", "就绪")
        with self.assertRaises(KeyError):
            translate("en", "missing translation")


if __name__ == "__main__":
    unittest.main()
