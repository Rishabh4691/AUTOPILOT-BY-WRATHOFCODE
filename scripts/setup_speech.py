import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mail import files  # noqa: E402


def line(ok: bool, name: str, detail: str) -> bool:
    print(f"[{'ok' if ok else '--'}] {name}: {detail}")
    return ok


def main() -> int:
    ffmpeg = files._ffmpeg()
    line(bool(ffmpeg), "ffmpeg", ffmpeg or "missing: winget install Gyan.FFmpeg / apt install ffmpeg / brew install ffmpeg")
    tesseract = shutil.which("tesseract")
    line(bool(tesseract), "tesseract (OCR)", tesseract or "missing: winget install UB-Mannheim.TesseractOCR / apt install tesseract-ocr")
    try:
        import faster_whisper  # noqa: F401

        start = time.monotonic()
        ready = files.warm_speech()
        line(ready, "faster-whisper", f"model {os.getenv('WHISPER_MODEL', 'small')} loaded in {time.monotonic() - start:.0f} s")
    except ImportError:
        ready = False
        line(False, "faster-whisper", "missing: pip install -r requirements.txt")
    if not ready and os.name == "nt":
        script = Path(__file__).with_name("stt.ps1")
        run = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; "
             "[System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | % { $_.Culture.Name }"],
            capture_output=True, text=True, timeout=60,
        )
        langs = run.stdout.split()
        line(bool(langs), "Windows speech fallback", f"{script.name}, recognizers: {', '.join(langs) or 'none'}")
    sample = sys.argv[1] if len(sys.argv) > 1 else None
    if sample:
        text = files.file_text(Path(sample).name, Path(sample).read_bytes())
        print(f"\n{sample} ->\n{text or '(nothing read)'}")
    return 0 if ffmpeg and (ready or os.name == "nt") else 1


if __name__ == "__main__":
    sys.exit(main())
