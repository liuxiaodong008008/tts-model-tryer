from __future__ import annotations

import io
import json
import tarfile
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from tts_backend import (
    AUDITION_LANGUAGES, LANGUAGE_NAMES, MODELS, PRESETS, Asset, DownloadCancelled, Engine, ModelStore, Request,
    audition_requests, clip_audio, download, extract_archive, load_reference, read_result, validate_request,
)


class BackendTests(unittest.TestCase):
    def test_catalog_covers_seven_families(self) -> None:
        self.assertEqual({m.family for m in MODELS}, {
            "kokoro", "matcha", "zipvoice", "kitten", "pocket", "piper", "supertonic",
        })
        self.assertEqual(len({m.key for m in MODELS}), len(MODELS))

    def test_twenty_language_audition_plan(self) -> None:
        requests = audition_requests(threads=3)
        self.assertEqual(len(requests), 20)
        self.assertEqual(len({request.language for request in requests}), 20)
        self.assertEqual(tuple(request.language for request in requests), AUDITION_LANGUAGES)
        for request in requests:
            with self.subTest(language=request.language):
                validate_request(request)
                self.assertEqual(request.threads, 3)
                self.assertEqual(request.text, PRESETS[request.language][0][1])
                self.assertTrue(LANGUAGE_NAMES[request.language])
                self.assertEqual(request.model_key, "kokoro" if request.language == "zh" else "supertonic")
        self.assertTrue(all(lang in LANGUAGE_NAMES for model in MODELS for lang in model.languages))

    def test_request_validation(self) -> None:
        valid = Request("kokoro", "你好。", "zh", sid=45)
        self.assertEqual(validate_request(valid).key, "kokoro")
        for changes in (
            {"text": ""}, {"language": "fr"}, {"sid": 53}, {"sid": -1},
            {"speed": 0}, {"speed": float("nan")}, {"threads": 0},
            {"steps": 33}, {"text": "x" * 5001},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_request(replace(valid, **changes))

    def test_english_model_rejects_chinese(self) -> None:
        with self.assertRaises(ValueError):
            validate_request(Request("kitten", "你好。", "en"))

    def test_zipvoice_custom_reference_requires_transcript(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as reference:
            with self.assertRaises(ValueError):
                validate_request(Request("zipvoice", "Hello.", "en", reference=reference.name))

    def test_clip_exact_sample_bounds(self) -> None:
        samples = np.arange(100, dtype=np.float32)
        np.testing.assert_array_equal(clip_audio(samples, 10, 2, 3), samples[20:50])
        np.testing.assert_array_equal(clip_audio(samples, 10, 8, 5), samples[80:])
        for start, duration in ((10, 1), (-1, 1), (0, 0), (float("nan"), 1)):
            with self.subTest(start=start, duration=duration), self.assertRaises(ValueError):
                clip_audio(samples, 10, start, duration)

    def test_reference_limits_and_builtin_crop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "reference.wav"
            samples = np.full((3100, 2), 0.1, dtype=np.float32)
            sf.write(path, samples, 100)
            with self.assertRaises(ValueError):
                load_reference(path)
            mono, rate = load_reference(path, built_in=True)
            self.assertEqual(rate, 100)
            self.assertEqual(mono.shape, (1000,))
            sf.write(path, np.zeros(100), 100)
            with self.assertRaises(ValueError):
                load_reference(path)

    def test_download_size_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "model"
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"1234")) as fetch:
                download(Asset("test", 4), target, lambda *args: None, threading.Event())
                download(Asset("test", 4), target, lambda *args: None, threading.Event())
                fetch.assert_called_once()
            self.assertEqual(target.read_bytes(), b"1234")
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"x")):
                with self.assertRaises(OSError):
                    download(Asset("bad", 3), target, lambda *args: None, threading.Event())
            self.assertFalse(target.with_name("model.part").exists())
            self.assertEqual(target.read_bytes(), b"1234")

    def test_download_cancellation_cleans_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cancel = threading.Event()
            cancel.set()
            target = Path(temp) / "model"
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"1234")):
                with self.assertRaises(DownloadCancelled):
                    download(Asset("test", 4), target, lambda *args: None, cancel)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name("model.part").exists())

    def test_archive_rejects_traversal_and_links(self) -> None:
        for member_name, link in (("model/../../outside", False), ("model/link", True)):
            with self.subTest(name=member_name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root / "test.tar.bz2"
                with tarfile.open(archive, "w:bz2") as tar:
                    member = tarfile.TarInfo(member_name)
                    if link:
                        member.type = tarfile.SYMTYPE
                        member.linkname = "outside"
                    tar.addfile(member)
                with self.assertRaises(ValueError):
                    extract_archive(archive, root / "dest", "model")

    def test_store_resumes_managed_partial_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "model.tar.bz2"
            with tarfile.open(archive, "w:bz2") as tar:
                member = tarfile.TarInfo("model/tokens.txt")
                member.size = 2
                tar.addfile(member, io.BytesIO(b"ok"))
            model = replace(MODELS[0], archive=Asset("model.tar.bz2", archive.stat().st_size), extras=())
            destination = root / "model"
            destination.mkdir()
            (destination / ".installing").write_text("test")
            store = ModelStore(root)
            store.prepare(model, lambda *args: None, threading.Event())
            self.assertTrue(store.ready(model))
            self.assertEqual((destination / "tokens.txt").read_text(), "ok")
            self.assertFalse((destination / ".installing").exists())

    def test_missing_models_never_trigger_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = Engine(ModelStore(Path(temp)))
            with patch("urllib.request.urlopen") as fetch:
                with self.assertRaises(FileNotFoundError):
                    engine.synthesize(Request("kitten", "Hello.", "en"), lambda *args: None, threading.Event())
                fetch.assert_not_called()

    def test_output_metadata_roundtrip_and_engine_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            engine = Engine(ModelStore(root / "models"), root / "outputs")
            samples = np.sin(np.arange(2400, dtype=np.float32) / 10) * 0.2
            fake = SimpleNamespace(generate=lambda *args: SimpleNamespace(samples=samples, sample_rate=24000))
            with (
                patch.object(engine.store, "ready", return_value=True),
                patch("tts_backend.create_config"),
                patch("tts_backend.sherpa.OfflineTts", return_value=fake) as constructor,
            ):
                stages = []
                for _ in range(2):
                    result = engine.synthesize(
                        Request("kitten", "Hello.", "en"), lambda *args: None,
                        threading.Event(), observe=stages.append,
                    )
                constructor.assert_called_once()
            self.assertEqual(stages, [
                "load_start", "load_end", "synthesis_start", "synthesis_end",
                "synthesis_start", "synthesis_end",
            ])
            loaded = read_result(result.path.with_suffix(".json"))
            self.assertEqual(loaded.request.text, "Hello.")
            self.assertEqual(loaded.sample_rate, 24000)
            self.assertAlmostEqual(loaded.duration, 0.1)
            data, _ = sf.read(loaded.path)
            self.assertGreater(float(np.max(np.abs(data))), 0.1)
            loaded.path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                read_result(loaded.path.with_suffix(".json"))


if __name__ == "__main__":
    unittest.main()
