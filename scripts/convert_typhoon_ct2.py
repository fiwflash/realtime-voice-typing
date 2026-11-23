"""Convert SCB 10X "Typhoon Whisper" models to CTranslate2 for faster-whisper.

The app (`realtime_voice_typing`) loads models through `faster-whisper`, which
needs the CTranslate2 format (`model.bin`). The official Typhoon Whisper models
are published as Transformers `safetensors`, so they must be converted once
before the app can download and use them.

Usage
-----
Install the converter dependencies (once):

    python -m pip install ctranslate2 transformers torch huggingface_hub

Convert a model (downloads the source weights first, ~1.6 GB turbo / ~3 GB large-v3):

    python scripts/convert_typhoon_ct2.py turbo
    python scripts/convert_typhoon_ct2.py large-v3

Optionally upload the result to Hugging Face so the app can download it through
its normal "จัดการโมเดล" flow:

    python scripts/convert_typhoon_ct2.py turbo --repo-id <you>/typhoon-whisper-turbo-ct2 --token <HF_WRITE_TOKEN>
    python scripts/convert_typhoon_ct2.py large-v3 --repo-id <you>/typhoon-whisper-large-v3-ct2 --token <HF_WRITE_TOKEN>

See docs/typhoon-whisper-setup.md for the full end-to-end guide.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# model key -> official Hugging Face repo id (Transformers format)
MODELS = {
    "turbo": "typhoon-ai/typhoon-whisper-turbo",
    "large-v3": "typhoon-ai/typhoon-whisper-large-v3",
}

# Files the app's model_manager._ALLOWED_PATTERNS expects next to model.bin.
COPY_FILES = ("tokenizer.json", "preprocessor_config.json")


def convert(model: str, output_dir: Path, quantization: str) -> Path:
    source = MODELS[model]
    if output_dir.exists():
        shutil.rmtree(output_dir)

    cmd = [
        "ct2-transformers-converter",
        "--model", source,
        "--output_dir", str(output_dir),
        "--copy_files", *COPY_FILES,
        "--quantization", quantization,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    if not (output_dir / "model.bin").is_file():
        sys.exit(f"Conversion finished but {output_dir / 'model.bin'} is missing — conversion failed.")
    print(f"Converted -> {output_dir}")
    return output_dir


def upload(folder: Path, repo_id: str, token: str | None) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="model", exist_ok=True)
    api.upload_folder(folder_path=str(folder), repo_id=repo_id, repo_type="model")
    print(f"Uploaded -> https://huggingface.co/{repo_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=sorted(MODELS), help="which Typhoon model to convert")
    parser.add_argument("--quantization", default="float16", help="CTranslate2 quantization (default float16)")
    parser.add_argument("--output-dir", default=None, help="output directory (default ct2-<model>)")
    parser.add_argument("--repo-id", default=None, help="Hugging Face repo to upload to (e.g. <you>/typhoon-whisper-turbo-ct2)")
    parser.add_argument("--token", default=None, help="Hugging Face write token (only needed with --repo-id)")
    args = parser.parse_args()

    out = Path(args.output_dir) if args.output_dir else Path(f"ct2-{args.model}")
    convert(args.model, out, args.quantization)

    if args.repo_id:
        upload(out, args.repo_id, args.token)


if __name__ == "__main__":
    main()
