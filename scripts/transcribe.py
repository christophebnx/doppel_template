"""Transcribe an audio/video file with faster-whisper (optional extra: `uv sync --extra audio`).

  transcribe.py inbox/_raw/2026-11-17_call.m4a [--model small] [--language fr]

Prints the transcript (with [mm:ss] timestamps) to stdout.
Exit code 3 when faster-whisper is not installed: the caller must then say so and keep the raw file.
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--model", default="small")
    ap.add_argument("--language", default="fr")
    args = ap.parse_args(argv)
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        print("faster-whisper not installed (run: uv sync --extra audio). Transcription unavailable.", file=sys.stderr)
        return 3
    model = WhisperModel(args.model, device="auto", compute_type="int8")
    segments, _ = model.transcribe(args.file, language=args.language, vad_filter=True)
    for seg in segments:
        m, s = divmod(int(seg.start), 60)
        print(f"[{m:02d}:{s:02d}] {seg.text.strip()}")
    return 0


if __name__ == "__main__":
    from common import run_main
    sys.exit(run_main(main, __file__))
