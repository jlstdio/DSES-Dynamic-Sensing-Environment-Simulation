#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
import zipfile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download environmental sound datasets.")
    parser.add_argument("--dataset", type=str, default="ASC24", choices=["ASC24"], help="Dataset option. Default: ASC24")
    parser.add_argument("--output-root", type=Path, default=Path.home() / "Downloads", help="Root directory for downloads.")
    parser.add_argument("--extract", action="store_true", help="Extract zip after download.")
    return parser.parse_args()


def download_asc24(output_root: Path, extract: bool) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    zip_path = output_root / "sounds-of-animals.zip"

    cmd = [
        "curl",
        "-L",
        "-o",
        str(zip_path),
        "https://www.kaggle.com/api/v1/datasets/download/haithammoh/sounds-of-animals",
    ]
    subprocess.run(cmd, check=True)

    extracted_dir = output_root / "sounds-of-animals"
    if extract:
        extracted_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extracted_dir)

    labels = []
    search_root = extracted_dir if extract else output_root
    audio_ext = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}
    if search_root.exists():
        labels = sorted(
            {
                file_path.parent.name
                for file_path in search_root.rglob("*")
                if file_path.is_file() and file_path.suffix.lower() in audio_ext
            }
        )

    return {
        "dataset": "ASC24",
        "zip_path": str(zip_path),
        "extracted_dir": str(extracted_dir),
        "labels_detected": labels,
        "note": "Kaggle API credentials are required (kaggle.json).",
    }


def main() -> None:
    args = parse_args()
    if args.dataset == "ASC24":
        report = download_asc24(args.output_root, args.extract)
    else:
        raise ValueError(f"Unsupported dataset: {args.dataset}")

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
