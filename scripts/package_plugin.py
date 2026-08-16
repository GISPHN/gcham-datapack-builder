#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

PLUGIN_DIR = "gcham_datapack_builder"
ROOT_DOCS = ("LICENSE", "README.md", "CHANGELOG.md", "DATA_SOURCES.md")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    package = root / PLUGIN_DIR
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(package).as_posix()
            zf.write(path, f"{PLUGIN_DIR}/{rel}")
        for name in ROOT_DOCS:
            zf.write(root / name, f"{PLUGIN_DIR}/{name}")
    print(args.output)


if __name__ == "__main__":
    main()
