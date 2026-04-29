"""CLI entry point for a3_keymaker.

Usage::

    a3_keymaker                              # copy extractor SQF to clipboard
    a3_keymaker <dump.txt> [--output ...] [--json ...]   # render the keymap

Run with no arguments to copy the extractor SQF to your clipboard so you
can paste it into Arma 3's Debug Console. After capturing the dump, run
again with the dump file path to merge it with the bundled wiki action
list and write a self-contained static HTML keymap.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import date
from importlib import resources
from pathlib import Path

from a3_keymaker.merger import build_report
from a3_keymaker.parser import DumpParseError, parse_dump
from a3_keymaker.render import render


def _default_output_path() -> Path:
    return Path(f"{date.today():%Y_%m_%d}-Arma3_Keymaker.html")


def _load_script_text() -> str:
    """Load the bundled extractor SQF from the installed package data."""
    return (
        resources.files("a3_keymaker")
        .joinpath("scripts/extract_all.sqf")
        .read_text(encoding="utf-8")
    )


def _copy_to_clipboard(text: str) -> None:
    """Copy ``text`` to the OS clipboard via the platform's native tool."""
    if sys.platform == "win32":
        # clip.exe expects UTF-16-LE for Unicode round-trip.
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
        return
    if sys.platform == "darwin":
        cmd = ["pbcopy"]
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
    elif shutil.which("xsel"):
        cmd = ["xsel", "--clipboard", "--input"]
    else:
        raise RuntimeError("no clipboard tool available (install xclip or xsel)")
    subprocess.run(cmd, input=text, encoding="utf-8", check=True)


def _copy_extractor_script() -> int:
    try:
        script = _load_script_text()
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        _copy_to_clipboard(script)
    except (RuntimeError, subprocess.SubprocessError) as e:
        print(f"error: failed to copy script to clipboard: {e}", file=sys.stderr)
        return 2
    print(
        "Keybind extraction script copied to clipboard. "
        "Paste it into Arma 3's Debug Console (LOCAL EXEC)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.dump is None:
        return _copy_extractor_script()

    try:
        text = args.dump.read_text(encoding="utf-8")
    except OSError as e:
        print(f"error: cannot read dump file {args.dump}: {e}", file=sys.stderr)
        return 2

    try:
        parsed = parse_dump(text)
    except DumpParseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    report = build_report(parsed, source_path=args.dump)

    args.output.write_text(render(report), encoding="utf-8")
    print(f"wrote {args.output} ({len(report.actions)} actions)")

    if args.json:
        args.json.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")

    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="a3_keymaker",
        description=(
            "Render an Arma 3 keybindings HTML keymap from a SQF dump. "
            "Run with no arguments to copy the extractor SQF to your clipboard."
        ),
    )
    p.add_argument(
        "dump",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Path to the A3KM_OK clipboard dump (text file). "
            "If omitted, the extractor SQF is copied to your clipboard instead."
        ),
    )
    p.add_argument(
        "-o", "--output",
        type=Path,
        default=_default_output_path(),
        help="Output HTML path (default: YYYY_MM_DD-Arma3_Keymaker.html in CWD).",
    )
    p.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Also emit the parsed keymap as JSON at this path.",
    )
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
