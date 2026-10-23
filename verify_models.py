from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import traceback
from unittest.mock import patch

import numpy as np

from tts_backend import LANGUAGE_NAMES, MODEL_BY_KEY, MODELS, PRESETS, ROOT, Engine, Request, audition_requests


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate real local audition clips for every model.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--models", nargs="+", choices=list(MODEL_BY_KEY), default=[m.key for m in MODELS])
    selection.add_argument("--audition-20", action="store_true", help="Generate 20 common-language audition clips.")
    args = parser.parse_args()
    engine = Engine()
    report = []
    requests = []
    if args.audition_20:
        requests.extend(audition_requests())
    else:
        for key in args.models:
            model = MODEL_BY_KEY[key]
            languages = ("zh", "en") if model.languages[:2] == ("zh", "en") else (model.languages[0],)
            for language in languages:
                requests.append(Request(
                    model_key=key, text=PRESETS[language][0][1], language=language,
                    sid=3 if key == "kokoro" and language == "en" else model.default_sid,
                    steps=8 if key == "supertonic" else 5,
                ))
    for request in requests:
        key, language = request.model_key, request.language
        print(f"VERIFY {key} {language}", flush=True)
        try:
            with patch("urllib.request.urlopen", side_effect=AssertionError("Synthesis must stay offline")):
                result = engine.synthesize(request, lambda *args: None, threading.Event())
            if result.duration < 0.2 or result.path.stat().st_size < 1000:
                raise AssertionError("Generated audio is too short.")
            rms = float(np.sqrt(np.mean(result.samples ** 2)))
            if rms < 1e-4:
                raise AssertionError("Generated audio is effectively silent.")
            row = {
                "model": key, "language": language, "language_name": LANGUAGE_NAMES[language],
                "text": request.text, "ok": True, "path": str(result.path),
                "duration": result.duration, "elapsed": result.elapsed,
                "rtf": result.rtf, "rms": rms, "sample_rate": result.sample_rate,
            }
            report.append(row)
            print(f"PASS {key}/{language}: {result.duration:.2f}s, RTF={result.rtf:.3f}, RMS={rms:.4f}", flush=True)
        except Exception as error:
            traceback.print_exc()
            report.append({"model": key, "language": language, "ok": False, "error": str(error)})
            print(f"FAIL {key}/{language}: {error}", flush=True)
    path = ROOT / "outputs" / ("audition-20.json" if args.audition_20 else "verification.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(not row["ok"] for row in report):
        raise SystemExit(1)
    print(f"ALL {len(report)} SYNTHESIS CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
