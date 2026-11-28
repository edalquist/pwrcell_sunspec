#!/usr/bin/env python3
"""Compile and verify the version-independent protobuf FileDescriptorSet.

Usage:
    python3 util/proto_descriptor.py          # Regenerate pwrcell/protos/energy_record_set.desc
    python3 util/proto_descriptor.py --check  # Verify .desc matches .proto (for CI)
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from google.protobuf import descriptor_pb2, text_format

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROTO_PATH = REPO_ROOT / "pwrcell" / "protos" / "energy_record_set.proto"
DEFAULT_DESC_PATH = REPO_ROOT / "pwrcell" / "protos" / "energy_record_set.desc"


def _strip_source_code_info(fds: descriptor_pb2.FileDescriptorSet) -> descriptor_pb2.FileDescriptorSet:
    """Clear source_code_info on all files for deterministic comparison across protoc versions."""
    for file_proto in fds.file:
        file_proto.ClearField("source_code_info")
    return fds


def compile_descriptor_set(
    proto_path: Path = DEFAULT_PROTO_PATH,
    protoc_bin: str = "protoc",
) -> descriptor_pb2.FileDescriptorSet:
    """Compile a .proto file with protoc and return its normalized FileDescriptorSet."""
    proto_path = Path(proto_path).resolve()
    if not proto_path.is_file():
        raise FileNotFoundError(f"Proto file not found: {proto_path}")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / f"{proto_path.stem}.desc"
        cmd = [
            protoc_bin,
            f"--proto_path={proto_path.parent}",
            "--include_imports",
            f"--descriptor_set_out={out_path}",
            proto_path.name,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        fds = descriptor_pb2.FileDescriptorSet()
        fds.ParseFromString(out_path.read_bytes())

    return _strip_source_code_info(fds)


def generate_descriptor(
    proto_path: Path = DEFAULT_PROTO_PATH,
    desc_path: Path = DEFAULT_DESC_PATH,
    protoc_bin: str = "protoc",
) -> Path:
    """Compile proto_path and write the serialized FileDescriptorSet to desc_path."""
    desc_path = Path(desc_path)
    fds = compile_descriptor_set(proto_path=proto_path, protoc_bin=protoc_bin)
    desc_path.parent.mkdir(parents=True, exist_ok=True)
    desc_path.write_bytes(fds.SerializeToString())
    return desc_path


def check_descriptor(
    proto_path: Path = DEFAULT_PROTO_PATH,
    desc_path: Path = DEFAULT_DESC_PATH,
    protoc_bin: str = "protoc",
) -> tuple[bool, str]:
    """Verify that desc_path semantically matches proto_path compiled with protoc."""
    proto_path = Path(proto_path)
    desc_path = Path(desc_path)

    if not desc_path.is_file():
        return (
            False,
            f"Descriptor file missing: {desc_path}. Run `python3 util/proto_descriptor.py` to generate it.",
        )

    fresh_fds = compile_descriptor_set(proto_path=proto_path, protoc_bin=protoc_bin)

    committed_fds = descriptor_pb2.FileDescriptorSet()
    committed_fds.ParseFromString(desc_path.read_bytes())
    _strip_source_code_info(committed_fds)

    if fresh_fds == committed_fds:
        return True, f"OK: {desc_path.name} is in sync with {proto_path.name}"

    committed_text = text_format.MessageToString(committed_fds).splitlines(keepends=True)
    fresh_text = text_format.MessageToString(fresh_fds).splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            committed_text,
            fresh_text,
            fromfile=str(desc_path),
            tofile=f"{proto_path} (compiled)",
        )
    )
    msg = (
        f"ERROR: {desc_path} is out of date with {proto_path}.\n"
        "Run `python3 util/proto_descriptor.py` and commit the updated .desc file.\n\n"
        f"{diff}"
    )
    return False, msg


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify the compiled protobuf FileDescriptorSet."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the committed .desc file matches the .proto source.",
    )
    parser.add_argument(
        "--protoc",
        default="protoc",
        help="Path or name of the protoc compiler binary (default: protoc).",
    )
    args = parser.parse_args(argv)

    try:
        if args.check:
            ok, message = check_descriptor(protoc_bin=args.protoc)
            print(message, file=sys.stdout if ok else sys.stderr)
            return 0 if ok else 1

        out_path = generate_descriptor(protoc_bin=args.protoc)
        print(f"Generated {out_path}")
        return 0
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        print(f"ERROR: protoc failed: {stderr}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
