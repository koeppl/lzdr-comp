#!/usr/bin/env python3
"""Benchmark the lower-bound string families from lzdr25.tex.

By default, run all power-of-two instances through k=256 and write CSV to
stdout. It records LZD, LZD+, and standard LZDR, invoking each scheme
individually so slower flexible variants do not delay these measurements.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


SCHEME_ORDER = ("LZD", "LZD+", "LZDR")
SCHEME_ALGORITHMS = {
    "LZD": ("lzd", "LZD (radix trie)"),
    "LZD+": ("lzd+", "LZD+ (linear-time)"),
    "LZDR": ("lzdr", "LZDR (radix trie)"),
}

# Factor counts reported in Table 3 (the Badkobeh-family S_k table).
# These are empirical table values, not a theorem for arbitrary k.
S_K_TABLE_COUNTS: Mapping[int, Mapping[str, int]] = {
    4: {"LZD": 24, "LZD+": 24, "LZDR": 24},
    8: {"LZD": 56, "LZD+": 56, "LZDR": 51},
    16: {"LZD": 144, "LZD+": 144, "LZDR": 99},
    32: {"LZD": 416, "LZD+": 416, "LZDR": 195},
    64: {"LZD": 1344, "LZD+": 1344, "LZDR": 387},
    128: {"LZD": 4736, "LZD+": 4736, "LZDR": 771},
    256: {"LZD": 17664, "LZD+": 17664, "LZDR": 1539},
}

CSV_FIELDS = (
    "family",
    "k",
    "input_bytes",
    "scheme",
    "observed_factors",
    "reference_factors",
    "reference_kind",
    "match",
)


class BenchmarkError(Exception):
    """An input, executable, or output-format error while running the bench."""


def _require_power_of_two(k: int, minimum: int, family: str) -> None:
    if k < minimum or (k & (k - 1)) != 0:
        raise ValueError("{} requires k to be a power of two >= {}".format(family, minimum))


def _delta(k: int, i: int) -> bytes:
    return b"a" * i + b"bb" + b"a" * (k - i)


def _gamma(i: int) -> bytes:
    return b"a" * i + b"bb"


def build_badkobeh(k: int) -> bytes:
    """Build S_k, the original Badkobeh family described in Section 3."""
    _require_power_of_two(k, 4, "S_k")

    prefix_parts: List[bytes] = []
    for i in range(2, k + 1):
        prefix_parts.extend((b"a" * i, b"c" * i))
    for i in range(k):
        prefix_parts.append(_gamma(i))
    for i in range(k + 1):
        prefix_parts.extend((_delta(k, i), b"d" * (i + 2)))

    m = k // 2
    hard_parts: List[bytes] = []
    for j in range(1, m):
        hard_parts.extend((_delta(k, k), _delta(k, k - j)))
    hard_parts.extend((_delta(k, k), b"a" * (k - 1)))

    return b"".join(prefix_parts) + b"".join(hard_parts) * m


def build_binary_lower_bound(k: int) -> bytes:
    """Build B_k, the rotated binary family from Section 6.1."""
    _require_power_of_two(k, 16, "B_k")

    m = k // 8
    tau = k // 2 + 1

    training_parts: List[bytes] = [b"bb", b"aa"]
    for r in range(3, k + 1):
        training_parts.extend((b"b" * r, b"a" * r))
    training_parts.append(b"b" * (k + 1))
    training_parts.extend(_gamma(i) for i in range(tau, k + 1))
    for i in range(tau, k):
        training_parts.extend((_delta(k, i), b"b" * (k // 2 + i + 1)))

    hard_parts: List[bytes] = []
    for j in range(1, m):
        hard_parts.extend((_delta(k, k), _delta(k, k - j)))
    hard_parts.extend((_delta(k, k), b"a" * (k - 1)))
    hard_part = b"".join(hard_parts)

    # rot_m(V) is the left rotation by m characters.
    rotated_hard_part = hard_part[m:] + hard_part[:m]
    return b"".join(training_parts) + rotated_hard_part * m


def binary_reference_count(k: int) -> int:
    """Return the exact factor count proved for B_k in the paper."""
    return 7 * k // 2 - 3 + k * k // 64


def _references(family: str, k: int) -> Tuple[Dict[str, Optional[int]], str]:
    if family == "B_k":
        count = binary_reference_count(k)
        return {scheme: count for scheme in SCHEME_ORDER}, "theorem"
    if k in S_K_TABLE_COUNTS:
        return dict(S_K_TABLE_COUNTS[k]), "paper_table"
    return {scheme: None for scheme in SCHEME_ORDER}, ""


def _parse_factor_count(output: str, heading: str) -> int:
    lines = output.splitlines()
    count_pattern = re.compile(r"^Num factors:\s*(\d+)\s*$")
    for index, line in enumerate(lines):
        if line.strip() == heading:
            for following_line in lines[index + 1 :]:
                match = count_pattern.match(following_line.strip())
                if match:
                    return int(match.group(1))
            break
    raise BenchmarkError("could not parse factor count after heading: {}".format(heading))


def _run_factor_counts(binary: Path, data: bytes) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for scheme, (algorithm, heading) in SCHEME_ALGORITHMS.items():
        try:
            result = subprocess.run(
                [str(binary), "-a", algorithm],
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as error:
            raise BenchmarkError("failed to run {}: {}".format(binary, error))

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            detail = stderr or stdout or "no diagnostic output"
            raise BenchmarkError(
                "{} ({}) exited with status {}: {}".format(
                    binary, algorithm, result.returncode, detail
                )
            )

        output = result.stdout.decode("utf-8", errors="replace")
        counts[scheme] = _parse_factor_count(output, heading)
    return counts


def _resolve_binary(argument: Optional[Path]) -> Path:
    repo_root = Path(__file__).resolve().parent
    if argument is None:
        return repo_root / "cmake-build" / "release" / "lzdr-comp"
    return argument.expanduser().resolve()


def _powers_of_two(minimum: int, maximum: int) -> Iterable[int]:
    value = minimum
    while value <= maximum:
        yield value
        value *= 2


def _record_family(
    writer: csv.DictWriter,
    binary: Path,
    family: str,
    k: int,
    data: bytes,
) -> bool:
    counts = _run_factor_counts(binary, data)
    references, reference_kind = _references(family, k)
    had_mismatch = False

    for scheme in SCHEME_ORDER:
        observed = counts[scheme]
        reference = references[scheme]
        matched = reference is not None and observed == reference
        writer.writerow(
            {
                "family": family,
                "k": k,
                "input_bytes": len(data),
                "scheme": scheme,
                "observed_factors": observed,
                "reference_factors": "" if reference is None else reference,
                "reference_kind": reference_kind,
                "match": "" if reference is None else str(matched).lower(),
            }
        )
        if reference is not None and not matched:
            print(
                "mismatch: family={}, k={}, scheme={}, expected={}, observed={}".format(
                    family, k, scheme, reference, observed
                ),
                file=sys.stderr,
            )
            had_mismatch = True

    return had_mismatch


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-k",
        type=int,
        default=256,
        help="largest power-of-two k to generate (default: 256; must be >= 16)",
    )
    parser.add_argument(
        "--binary",
        type=Path,
        help="lzdr-comp executable (default: cmake-build/release/lzdr-comp in the repo)",
    )
    args = parser.parse_args(argv)

    try:
        _require_power_of_two(args.max_k, 16, "--max-k")
    except ValueError as error:
        parser.error(str(error))

    binary = _resolve_binary(args.binary)
    if not binary.is_file():
        print("error: compressor executable not found: {}".format(binary), file=sys.stderr)
        return 1
    if not os.access(binary, os.X_OK):
        print("error: compressor is not executable: {}".format(binary), file=sys.stderr)
        return 1

    writer = csv.DictWriter(sys.stdout, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    had_mismatch = False

    try:
        for k in _powers_of_two(4, args.max_k):
            had_mismatch |= _record_family(writer, binary, "S_k", k, build_badkobeh(k))
            if k >= 16:
                had_mismatch |= _record_family(
                    writer, binary, "B_k", k, build_binary_lower_bound(k)
                )
    except BenchmarkError as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1

    return 1 if had_mismatch else 0


if __name__ == "__main__":
    raise SystemExit(main())
