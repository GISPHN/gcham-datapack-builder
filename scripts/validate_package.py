#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import io
from pathlib import Path, PurePosixPath
import re
import zipfile

PLUGIN_DIR = "gcham_datapack_builder"
REQUIRED = {"metadata.txt", "__init__.py", "LICENSE"}
ASCII_FOLDER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zipfile", type=Path)
    args = parser.parse_args()

    with zipfile.ZipFile(args.zipfile) as zf:
        bad = zf.testzip()
        if bad:
            raise SystemExit(f"Corrupt ZIP member: {bad}")
        names = [n for n in zf.namelist() if not n.endswith("/")]
        tops = {n.split("/", 1)[0] for n in names}
        if tops != {PLUGIN_DIR}:
            raise SystemExit(f"Unexpected top-level entries: {sorted(tops)}")
        if not ASCII_FOLDER.fullmatch(PLUGIN_DIR):
            raise SystemExit("Invalid plugin directory name")
        forbidden = [
            n
            for n in names
            if "__pycache__" in PurePosixPath(n).parts
            or n.endswith((".pyc", ".pyo"))
        ]
        if forbidden:
            raise SystemExit(f"Forbidden compiled Python files: {forbidden}")
        rels = {n.split("/", 1)[1] for n in names}
        missing = REQUIRED - rels
        if missing:
            raise SystemExit(f"Missing required files: {sorted(missing)}")

        metadata = zf.read(f"{PLUGIN_DIR}/metadata.txt").decode("utf-8")
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_file(io.StringIO(metadata))
        general = cp["general"]
        required_fields = [
            "name",
            "qgisMinimumVersion",
            "description",
            "about",
            "version",
            "author",
            "email",
            "repository",
            "tracker",
            "homepage",
        ]
        empty = [key for key in required_fields if not general.get(key, "").strip()]
        if empty:
            raise SystemExit(f"Missing/empty metadata: {empty}")
        if general.get("experimental", "").strip().lower() != "false":
            raise SystemExit("Stable package must set experimental=False")
        if general.get("version") != "1.1.2":
            raise SystemExit(f"Unexpected version: {general.get('version')}")
    print("Package validation passed")


if __name__ == "__main__":
    main()
