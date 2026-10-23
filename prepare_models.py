from __future__ import annotations

import argparse
import io
import logging
import sys
import threading

from tts_backend import MODELS, ModelStore


def main() -> None:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Download all TTS models for offline use.")
    parser.add_argument("--check", action="store_true", help="Check local models without network access.")
    args = parser.parse_args()
    store = ModelStore()

    def progress(name: str, received: int, total: int) -> None:
        if total:
            print(f"\r{name}: {received / 1e6:.1f}/{total / 1e6:.1f} MB", end="", flush=True)
            if received == total:
                print()
        else:
            print(f"\n{name}", flush=True)

    if args.check:
        missing = []
        for model in MODELS:
            ready = store.ready(model)
            print(f"{model.key}: {'READY' if ready else 'MISSING'}")
            if not ready:
                missing.append(model.key)
        if missing:
            raise SystemExit("Missing models: " + ", ".join(missing))
        return
    cancel = threading.Event()
    for index, model in enumerate(MODELS, 1):
        print(f"\n[{index}/{len(MODELS)}] {model.key}", flush=True)
        store.prepare(model, progress, cancel)
    print(f"\nAll models ready: {store.root}", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
