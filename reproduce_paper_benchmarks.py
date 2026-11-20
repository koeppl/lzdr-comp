#!/usr/bin/env python3
"""Reproduce the benchmark tables and plots described in lzdr25.tex.

The default run writes three reports into benchmark-results/:

* synthetic-lower-bounds.csv: the S_k and B_k families;
* factor-counts.csv: raw factor counts and percentages relative to LZD;
* speed-memory.csv and speed-memory.raw.json: median time and peak memory.

The practical factor-count runs use Calgary, Canterbury, and the Pizza&Chili
prefix files listed in the paper. Runtime and memory use the five Pizza&Chili
families plotted in the paper, with 50, 100, and 200 MiB inputs.

By default, missing project binaries are built and missing corpus files are
downloaded. Use --no-prepare to require all prerequisites to be present.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "benchmark-results"

MAIN_SCHEMES: Mapping[str, Tuple[str, str]] = {
    "LZDR greedy": ("lzdr", "LZDR (radix trie)"),
    "LZDR StdFlex": ("lzdr-std-flex", "Standard Flexible LZDR (radix trie)"),
    "LZDR AltFlex": ("lzdr-alt-flex", "Alternative Flexible LZDR (radix trie)"),
    "LZDR MaxAlt": ("lzdr-max-alt", "Alternative Flexible LZDR Max. (radix trie)"),
    "LZD+": ("lzd+", "LZD+ (linear-time)"),
    "LZD": ("lzd", "LZD (radix trie)"),
    "LZW StdFlex": ("lzw-std-flex", "Standard Flexible LZW (naive)"),
    "LZW AltFlex": ("lzw-alt-flex", "Alternative Flexible LZW (naive)"),
}
SCHEME_ORDER = (
    "LZDR greedy",
    "LZDR StdFlex",
    "LZDR AltFlex",
    "LZDR MaxAlt",
    "LZD+",
    "LZD",
    "LZ78",
    "LZW greedy",
    "LZW StdFlex",
    "LZW AltFlex",
)

CALGARY_FILES = (
    "bib", "book1", "book2", "geo", "news", "obj1", "obj2",
    "paper1", "paper2", "paper3", "paper4", "paper5", "paper6",
    "pic", "progc", "progl", "progp", "trans",
)
CANTERBURY_FILES = (
    "alice29.txt", "asyoulik.txt", "cp.html", "fields.c", "grammar.lsp",
    "kennedy.xls", "lcet10.txt", "plrabn12.txt", "sum", "xargs.1",
)

# Factor-count table inputs from the Pizza&Chili part of the paper.
PIZZA_FACTOR_FILES = (
    ("sources", "sources", (50, 100, 200)),
    ("pitches", "pitches", (50,)),
    ("proteins", "proteins", (50, 100, 200)),
    ("dna", "dna", (50, 100, 200)),
    ("english", "english", (50, 100, 200)),
    ("xml", "dblp.xml", (50, 100, 200)),
)

# The paper's time and memory plots contain five families at each size.
PIZZA_PERFORMANCE_FAMILIES = (
    ("dna", "dna"),
    ("english", "english"),
    ("proteins", "proteins"),
    ("sources", "sources"),
    ("xml", "dblp.xml"),
)
PIZZA_PERFORMANCE_SIZES = (50, 100, 200)
PIZZA_DOWNLOAD_DIRECTORIES = {
    "sources": "code",
    "pitches": "music",
    "proteins": "protein",
    "dna": "dna",
    "english": "nlang",
    "xml": "xml",
}
PIZZA_TEXTS_URL = "https://pizzachili.dcc.uchile.cl/texts"
CALGARY_ARCHIVE_URL = "https://corpus.canterbury.ac.nz/resources/calgary.tar.gz"
CANTERBURY_ARCHIVE_URL = "https://corpus.canterbury.ac.nz/resources/cantrbry.tar.gz"

COUNT_FIELDS = (
    "corpus",
    "dataset",
    "input_bytes",
    "sha256",
    "scheme",
    "factor_count",
    "relative_to_lzd_percent",
    "status",
)
PERFORMANCE_FIELDS = (
    "dataset",
    "input_bytes",
    "sha256",
    "compressor",
    "median_time_seconds",
    "peak_memory_bytes",
    "peak_memory_mib",
)


class BenchmarkError(Exception):
    """A missing dependency, dataset, or invalid benchmark result."""


PAPER_UNFINISHED_COUNTS = {
    ("datasets/pizza-chili/xml/dblp.xml.100MB", "LZDR AltFlex"),
    ("datasets/pizza-chili/xml/dblp.xml.200MB", "LZDR AltFlex"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pizza_path(dataset_dir: str, basename: str, size_mib: int) -> Path:
    suffix = ".{}MB".format(size_mib)
    return ROOT / "datasets" / "pizza-chili" / dataset_dir / (basename + suffix)


def _required_dataset_inputs(stage: str) -> List[Path]:
    paths: List[Path] = []
    if stage in ("all", "counts"):
        paths.extend(path for _, path in _factor_count_inputs())
    if stage in ("all", "performance"):
        paths.extend(_performance_inputs())
    return list(dict.fromkeys(paths))


def _pizza_download_urls() -> Dict[Path, str]:
    downloads: Dict[Path, str] = {}
    for dataset_dir, basename, sizes in PIZZA_FACTOR_FILES:
        source_dir = PIZZA_DOWNLOAD_DIRECTORIES[dataset_dir]
        for size in sizes:
            filename = "{}.{}MB".format(basename, size)
            downloads[_pizza_path(dataset_dir, basename, size)] = (
                "{}/{}/{}.gz".format(PIZZA_TEXTS_URL, source_dir, filename)
            )
    return downloads


def _valid_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _download_gzip_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    print("[prepare] Downloading {}".format(url), file=sys.stderr)
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=60) as response:
            with gzip.GzipFile(fileobj=response) as contents:
                with temporary.open("wb") as output:
                    copied = 0
                    next_report = 64 * 1024 * 1024
                    while True:
                        chunk = contents.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        copied += len(chunk)
                        if copied >= next_report:
                            print(
                                "[prepare] Downloaded {:.0f} MiB for {}".format(
                                    copied / (1024 * 1024), destination.name
                                ),
                                file=sys.stderr,
                            )
                            next_report += 64 * 1024 * 1024
        if temporary.stat().st_size == 0:
            raise BenchmarkError("download produced an empty file: {}".format(url))
        os.replace(str(temporary), str(destination))
    except (OSError, EOFError, HTTPException, URLError, gzip.BadGzipFile, zlib.error) as error:
        raise BenchmarkError(
            "failed to download {} for {}: {}".format(url, destination, error)
        )
    finally:
        temporary.unlink(missing_ok=True)
    print("[prepare] Ready: {}".format(destination.relative_to(ROOT)), file=sys.stderr)


def _download_and_extract_archive(
    url: str, destination_dir: Path, required_names: Sequence[str]
) -> None:
    if not required_names:
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    remaining = set(required_names)
    print("[prepare] Downloading {}".format(url), file=sys.stderr)
    try:
        with tempfile.TemporaryDirectory(prefix="lzdr-benchmark-") as temporary_dir:
            archive_path = Path(temporary_dir) / "corpus.tar.gz"
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=60) as response, archive_path.open("wb") as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
            with tarfile.open(str(archive_path), mode="r:gz") as archive:
                for member in archive:
                    filename = Path(member.name).name
                    if not member.isfile() or filename not in remaining:
                        continue
                    contents = archive.extractfile(member)
                    if contents is None:
                        continue
                    destination = destination_dir / filename
                    partial = destination.with_name(destination.name + ".part")
                    try:
                        with contents, partial.open("wb") as output:
                            shutil.copyfileobj(contents, output, 1024 * 1024)
                        if partial.stat().st_size == 0:
                            raise BenchmarkError(
                                "archive contained an empty file: {}".format(filename)
                            )
                        os.replace(str(partial), str(destination))
                    finally:
                        partial.unlink(missing_ok=True)
                    remaining.remove(filename)
                    print(
                        "[prepare] Ready: {}".format(destination.relative_to(ROOT)),
                        file=sys.stderr,
                    )
    except (OSError, EOFError, HTTPException, URLError, tarfile.TarError) as error:
        raise BenchmarkError("failed to fetch corpus archive {}: {}".format(url, error))
    if remaining:
        raise BenchmarkError(
            "{} did not contain required file(s): {}".format(
                url, ", ".join(sorted(remaining))
            )
        )


def _prepare_dataset_inputs(paths: Sequence[Path]) -> None:
    missing = [path for path in paths if not _valid_file(path)]
    if not missing:
        print("[prepare] Benchmark datasets are already present.", file=sys.stderr)
        return

    pizza_urls = _pizza_download_urls()
    pizza_missing = [path for path in missing if path in pizza_urls]
    for path in pizza_missing:
        _download_gzip_file(pizza_urls[path], path)

    calgary_missing = [
        path.name
        for path in missing
        if path.parent == ROOT / "datasets" / "calgary"
    ]
    canterbury_missing = [
        path.name
        for path in missing
        if path.parent == ROOT / "datasets" / "canterbury"
    ]
    _download_and_extract_archive(
        CALGARY_ARCHIVE_URL,
        ROOT / "datasets" / "calgary",
        calgary_missing,
    )
    _download_and_extract_archive(
        CANTERBURY_ARCHIVE_URL,
        ROOT / "datasets" / "canterbury",
        canterbury_missing,
    )

    unknown = [path for path in missing if path not in pizza_urls and path.parent not in (
        ROOT / "datasets" / "calgary",
        ROOT / "datasets" / "canterbury",
    )]
    if unknown:
        raise BenchmarkError(
            "no automatic download source for required input(s): {}".format(
                ", ".join(str(path) for path in unknown)
            )
        )


def _factor_count_inputs() -> List[Tuple[str, Path]]:
    inputs: List[Tuple[str, Path]] = []
    for filename in CALGARY_FILES:
        inputs.append(("Calgary", ROOT / "datasets" / "calgary" / filename))
    for filename in CANTERBURY_FILES:
        inputs.append(("Canterbury", ROOT / "datasets" / "canterbury" / filename))
    for dataset_dir, basename, sizes in PIZZA_FACTOR_FILES:
        for size in sizes:
            inputs.append(
                (
                    "Pizza&Chili",
                    _pizza_path(dataset_dir, basename, size),
                )
            )
    return inputs


def _performance_inputs() -> List[Path]:
    return [
        _pizza_path(dataset_dir, basename, size)
        for dataset_dir, basename in PIZZA_PERFORMANCE_FAMILIES
        for size in PIZZA_PERFORMANCE_SIZES
    ]


def _require_files(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise BenchmarkError(
            "required benchmark input(s) are missing:\n  " + "\n  ".join(missing)
        )


def _require_executable(path: Path, label: str) -> None:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise BenchmarkError(
            "{} executable not found or not executable: {}".format(label, path)
        )


def _run_prepare_command(
    command: Sequence[str], cwd: Path, env: Optional[Mapping[str, str]] = None
) -> None:
    print("[prepare] Running: {}".format(" ".join(command)), file=sys.stderr)
    try:
        result = subprocess.run(command, cwd=str(cwd), env=env, check=False)
    except OSError as error:
        raise BenchmarkError("could not start {}: {}".format(command[0], error))
    if result.returncode != 0:
        raise BenchmarkError(
            "preparation command failed with status {}: {}".format(
                result.returncode, " ".join(command)
            )
        )


def _prepare_lzdr_binary(binary: Path) -> None:
    _run_prepare_command(
        ["cmake", "-S", ".", "-B", str(binary.parent), "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF"],
        ROOT,
    )
    _run_prepare_command(
        ["cmake", "--build", str(binary.parent), "--parallel", str(os.cpu_count() or 1)],
        ROOT,
    )


def _prepare_lzd_binary(binary: Path) -> None:
    source_dir = ROOT / "subprojects" / "lzd"
    sconstruct = source_dir / "SConstruct"
    makefile = source_dir / "src" / "lcacomp" / "Makefile"
    if not sconstruct.is_file() or not makefile.is_file():
        raise BenchmarkError(
            "LZD submodule source is missing; run `git submodule update --init --recursive`."
        )

    sconstruct_text = sconstruct.read_text(encoding="utf-8")
    sconstruct_text = re.sub(
        r"(?m)^([ \t]*)print ([^()\n]*)$", r"\1print(\2)", sconstruct_text
    )
    sconstruct_text = sconstruct_text.replace(
        "type(srcs) != types.ListType", "not isinstance(srcs, list)"
    )
    sconstruct_text = sconstruct_text.replace("-Ofast", "-O3")
    sconstruct.write_text(sconstruct_text, encoding="utf-8")
    makefile.write_text(
        makefile.read_text(encoding="utf-8").replace("-Ofast", "-O3"),
        encoding="utf-8",
    )
    _run_prepare_command(
        ["scons", "-j{}".format(os.cpu_count() or 1)], source_dir
    )


def _prepare_tudocomp_binary(binary: Path) -> None:
    source_dir = ROOT / "subprojects" / "tudocomp"
    patch = ROOT / "subprojects" / "tudocomp-fix-build.patch"
    cmake_file = source_dir / "CMakeLists.txt"
    if not cmake_file.is_file() or not patch.is_file():
        raise BenchmarkError(
            "tudocomp submodule source or compatibility patch is missing; "
            "run `git submodule update --init --recursive`."
        )

    patch_result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=localhost",
            "-c",
            "user.email=<>",
            "am",
            str(patch),
        ],
        cwd=str(source_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if patch_result.returncode != 0:
        subprocess.run(
            ["git", "am", "--abort"],
            cwd=str(source_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    cmake_file.write_text(
        re.sub(
            r" ?-march=native",
            "",
            cmake_file.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CXXFLAGS"] = "-std=gnu++14"
    _run_prepare_command(
        ["cmake", "-S", ".", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
        source_dir,
        env,
    )
    _run_prepare_command(
        [
            "cmake",
            "--build",
            "build",
            "--target",
            "tudocomp_driver",
            "--parallel",
            str(os.cpu_count() or 1),
        ],
        source_dir,
        env,
    )


def _preparation_commands_needed(
    missing_binaries: Sequence[Tuple[str, Path]],
    need_submodule_init: bool,
) -> List[str]:
    commands = set()
    labels = {label for label, _ in missing_binaries}
    if "lzdr-comp" in labels or "tudocomp" in labels:
        commands.update(("cmake", "make"))
        if shutil.which("c++") is None and shutil.which("g++") is None:
            commands.add("c++ or g++")
    if "LZD" in labels:
        commands.update(("scons", "clang"))
    if "tudocomp" in labels or need_submodule_init:
        commands.add("git")
    return sorted(command for command in commands if shutil.which(command) is None)


def _prepare_prerequisites(
    stage: str,
    required_files: Sequence[Path],
    binaries: Sequence[Tuple[str, Path]],
    prepare: bool,
) -> None:
    missing_files = [path for path in required_files if not _valid_file(path)]
    missing_binaries = [
        (label, path)
        for label, path in binaries
        if not path.is_file() or not os.access(path, os.X_OK)
    ]
    needs_submodule_init = bool(missing_binaries) and (
        not (ROOT / "subprojects" / "lzd" / "SConstruct").is_file()
        or not (ROOT / "subprojects" / "tudocomp" / "CMakeLists.txt").is_file()
    )

    missing_commands = _preparation_commands_needed(
        missing_binaries, needs_submodule_init
    )
    if stage in ("all", "performance") and shutil.which("valgrind") is None:
        missing_commands.append("valgrind")

    if not prepare:
        problems = []
        if missing_binaries:
            problems.append(
                "missing executable(s): {}".format(
                    ", ".join("{} ({})".format(label, path) for label, path in missing_binaries)
                )
            )
        if missing_files:
            problems.append(
                "missing dataset file(s): {}".format(
                    ", ".join(str(path) for path in missing_files)
                )
            )
        if missing_commands:
            problems.append(
                "missing system tool(s): {}".format(", ".join(sorted(set(missing_commands))))
            )
        if problems:
            raise BenchmarkError(
                "--no-prepare requested, but prerequisites are incomplete:\n  "
                + "\n  ".join(problems)
                + "\nRemove --no-prepare to build/download project files; install "
                "missing system tools separately."
            )
        print("[prepare] Prerequisites are present (--no-prepare).", file=sys.stderr)
        return

    if missing_commands:
        raise BenchmarkError(
            "cannot prepare automatically; install missing system tool(s): {}. "
            "On Ubuntu, see the package list in Dockerfile.".format(
                ", ".join(sorted(set(missing_commands)))
            )
        )

    if needs_submodule_init:
        _run_prepare_command(
            ["git", "submodule", "update", "--init", "--recursive"], ROOT
        )

    for label, path in missing_binaries:
        print("[prepare] Building missing {}.".format(label), file=sys.stderr)
        if label == "lzdr-comp":
            _prepare_lzdr_binary(path)
        elif label == "LZD":
            _prepare_lzd_binary(path)
        elif label == "tudocomp":
            _prepare_tudocomp_binary(path)
        _require_executable(path, label)

    if missing_files:
        _prepare_dataset_inputs(missing_files)
        still_missing = [path for path in missing_files if not _valid_file(path)]
        if still_missing:
            raise BenchmarkError(
                "dataset preparation did not provide required file(s): {}".format(
                    ", ".join(str(path) for path in still_missing)
                )
            )
    else:
        print("[prepare] Required benchmark datasets are present.", file=sys.stderr)


def _parse_single_main_count(output: str, path: Path, scheme: str, heading: str) -> int:
    lines = output.splitlines()
    count_line = re.compile(r"^Num factors:\s*(\d+)\s*$")
    for index, line in enumerate(lines):
        if line.strip() != heading:
            continue
        for following_line in lines[index + 1 :]:
            match = count_line.match(following_line.strip())
            if match:
                return int(match.group(1))
        break
    raise BenchmarkError(
        "lzdr-comp did not report a factor count for {} on {}".format(scheme, path)
    )


def _run_main_factor_count(
    binary: Path, path: Path, scheme: str, algorithm: str, heading: str
) -> int:
    try:
        with path.open("rb") as source:
            result = subprocess.run(
                [str(binary), "-a", algorithm],
                stdin=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
    except OSError as error:
        raise BenchmarkError("failed to run lzdr-comp on {}: {}".format(path, error))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise BenchmarkError(
            "lzdr-comp failed on {} (status {}): {}".format(
                path, result.returncode, detail
            )
        )
    return _parse_single_main_count(result.stdout, path, scheme, heading)


def _run_main_factor_counts(binary: Path, path: Path) -> Dict[str, Optional[int]]:
    relative_path = path.relative_to(ROOT).as_posix()
    counts: Dict[str, Optional[int]] = {}
    for scheme, (algorithm, heading) in MAIN_SCHEMES.items():
        if (relative_path, scheme) in PAPER_UNFINISHED_COUNTS:
            counts[scheme] = None
            continue
        counts[scheme] = _run_main_factor_count(
            binary, path, scheme, algorithm, heading
        )
    return counts


def _run_tudocomp_count(binary: Path, path: Path, algorithm: str) -> int:
    command = [
        str(binary),
        "-a",
        "{}(coder=ascii)".format(algorithm),
        "-s",
        "--raw",
        "-f",
        "-o",
        os.devnull,
        "--",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as error:
        raise BenchmarkError("failed to run tudocomp on {}: {}".format(path, error))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise BenchmarkError(
            "tudocomp {} failed on {} (status {}): {}".format(
                algorithm, path, result.returncode, detail
            )
        )

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BenchmarkError(
            "could not parse tudocomp {} output for {}: {}".format(
                algorithm, path, error
            )
        )
    for phase in report.get("data", {}).get("sub", []):
        for stat in phase.get("stats", []):
            if stat.get("key") == "factor_count":
                return int(stat["value"])
    raise BenchmarkError(
        "tudocomp {} output has no factor_count for {}".format(algorithm, path)
    )


def _write_factor_counts(
    output_path: Path,
    inputs: Sequence[Tuple[str, Path]],
    lzdr_binary: Path,
    tdc_binary: Path,
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=COUNT_FIELDS, lineterminator="\n")
        writer.writeheader()

        for corpus, path in inputs:
            relative_path = path.relative_to(ROOT).as_posix()
            print("[factor counts] {}".format(relative_path), file=sys.stderr)
            main_counts = _run_main_factor_counts(lzdr_binary, path)
            counts = dict(main_counts)
            counts["LZ78"] = _run_tudocomp_count(tdc_binary, path, "lz78")
            counts["LZW greedy"] = _run_tudocomp_count(tdc_binary, path, "lzw")
            lzd_count = counts["LZD"]
            if lzd_count is None:
                raise BenchmarkError("LZD count is unavailable for {}".format(path))
            if lzd_count == 0:
                raise BenchmarkError("LZD returned zero factors for {}".format(path))

            input_bytes = path.stat().st_size
            digest = _sha256(path)
            for scheme in SCHEME_ORDER:
                factor_count = counts[scheme]
                percentage = (
                    ""
                    if factor_count is None
                    else "{:.2f}".format((factor_count / lzd_count - 1.0) * 100.0)
                )
                writer.writerow(
                    {
                        "corpus": corpus,
                        "dataset": relative_path,
                        "input_bytes": input_bytes,
                        "sha256": digest,
                        "scheme": scheme,
                        "factor_count": "" if factor_count is None else factor_count,
                        "relative_to_lzd_percent": percentage,
                        "status": (
                            "paper_n/a_timeout"
                            if factor_count is None
                            else "measured"
                        ),
                    }
                )
                row_count += 1
            output.flush()

    return row_count


def _write_synthetic_counts(
    output_path: Path, lzdr_binary: Path, max_k: int
) -> None:
    script = ROOT / "benchmark_lower_bound.py"
    if not script.is_file():
        raise BenchmarkError("synthetic lower-bound script not found: {}".format(script))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(script),
        "--max-k",
        str(max_k),
        "--binary",
        str(lzdr_binary),
    ]
    print("[synthetic lower bounds] k <= {}".format(max_k), file=sys.stderr)
    try:
        with output_path.open("w", encoding="utf-8", newline="") as output:
            result = subprocess.run(
                command,
                cwd=str(ROOT),
                stdout=output,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
    except OSError as error:
        raise BenchmarkError("failed to run lower-bound script: {}".format(error))
    if result.returncode != 0:
        detail = result.stderr.strip() or "no diagnostic output"
        raise BenchmarkError(
            "lower-bound benchmark failed (status {}): {}".format(
                result.returncode, detail
            )
        )


def _parse_number(value: object, *, field: str, dataset: str, compressor: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise BenchmarkError(
            "invalid {} for {} / {}: {!r}".format(field, dataset, compressor, value)
        )


def _write_performance(
    output_path: Path,
    raw_json_path: Path,
    files: Sequence[Path],
    iterations: int,
) -> int:
    if shutil.which("valgrind") is None:
        raise BenchmarkError(
            "Valgrind is required for the paper's maximum-memory measurements"
        )
    helper = ROOT / "bench_speed_mem.py"
    if not helper.is_file():
        raise BenchmarkError("speed/memory helper not found: {}".format(helper))

    command = [
        sys.executable,
        str(helper),
        "--iterations",
        str(iterations),
        "--format",
        "json",
    ] + [path.relative_to(ROOT).as_posix() for path in files]
    print(
        "[runtime and memory] {} inputs, median of {} runs".format(
            len(files), iterations
        ),
        file=sys.stderr,
    )
    try:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as error:
        raise BenchmarkError("failed to run speed/memory helper: {}".format(error))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise BenchmarkError(
            "speed/memory benchmark failed (status {}): {}".format(
                result.returncode, detail
            )
        )
    try:
        raw_report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BenchmarkError("could not parse speed/memory report: {}".format(error))

    raw_json_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_json_path.open("w", encoding="utf-8") as raw_output:
        json.dump(raw_report, raw_output, indent=2, sort_keys=True)
        raw_output.write("\n")

    expected_paths = {path.relative_to(ROOT).as_posix(): path for path in files}
    reported_files = raw_report.get("files", {})
    missing = sorted(set(expected_paths) - set(reported_files))
    if missing:
        raise BenchmarkError(
            "speed/memory report is missing input(s): {}".format(", ".join(missing))
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with output_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output, fieldnames=PERFORMANCE_FIELDS, lineterminator="\n"
        )
        writer.writeheader()

        for dataset, path in expected_paths.items():
            columns = reported_files[dataset].get("cols", {})
            compressors = columns.get("Compressor", [])
            times = columns.get("C Time", [])
            memories = columns.get("C Memory", [])
            if len(compressors) != len(times) or len(compressors) != len(memories):
                raise BenchmarkError(
                    "incomplete speed/memory columns for {}".format(dataset)
                )
            input_bytes = path.stat().st_size
            digest = reported_files[dataset].get("hash", _sha256(path))
            for compressor, elapsed, memory in zip(compressors, times, memories):
                # bench_speed_mem.py stores C Time in milliseconds in JSON.
                elapsed_seconds = _parse_number(
                    elapsed,
                    field="execution time",
                    dataset=dataset,
                    compressor=compressor,
                ) / 1000.0
                memory_bytes = _parse_number(
                    memory,
                    field="peak memory",
                    dataset=dataset,
                    compressor=compressor,
                )
                writer.writerow(
                    {
                        "dataset": dataset,
                        "input_bytes": input_bytes,
                        "sha256": digest,
                        "compressor": compressor,
                        "median_time_seconds": "{:.9f}".format(elapsed_seconds),
                        "peak_memory_bytes": int(memory_bytes),
                        "peak_memory_mib": "{:.2f}".format(memory_bytes / (1024 * 1024)),
                    }
                )
                row_count += 1

    return row_count


def _write_metadata(output_path: Path, args: argparse.Namespace) -> None:
    metadata = {
        "source": "lzdr25.tex, Section 6.1 and Practical benchmarks",
        "stage": args.stage,
        "synthetic_max_k": args.max_k,
        "performance_iterations": args.iterations,
        "host": platform.uname()._asdict(),
        "python": sys.version,
        "executables": {
            "lzdr-comp": "cmake-build/release/lzdr-comp",
            "lzd": "subprojects/lzd/out/lzd",
            "tudocomp": "subprojects/tudocomp/build/tdc",
        },
        "paper_unfinished_counts": [
            {"dataset": dataset, "scheme": scheme, "status": "paper_n/a_timeout"}
            for dataset, scheme in sorted(PAPER_UNFINISHED_COUNTS)
        ],
    }
    with output_path.open("w", encoding="utf-8") as output:
        json.dump(metadata, output, indent=2, sort_keys=True)
        output.write("\n")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("all", "counts", "performance"),
        default="all",
        help="run all paper results, factor counts only, or runtime/memory only",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="runtime repetitions; paper uses the median of five (default: 5)",
    )
    parser.add_argument(
        "--max-k",
        type=int,
        default=256,
        help="largest synthetic lower-bound parameter (default: 256)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="directory for CSV and JSON reports (default: benchmark-results/)",
    )
    parser.add_argument(
        "--no-prepare",
        dest="prepare",
        action="store_false",
        default=True,
        help="skip automatic builds/downloads and fail if prerequisites are missing",
    )
    args = parser.parse_args(argv)
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    if args.max_k < 16 or (args.max_k & (args.max_k - 1)) != 0:
        parser.error("--max-k must be a power of two >= 16")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    output_dir = args.output_dir.expanduser()
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    lzdr_binary = ROOT / "cmake-build" / "release" / "lzdr-comp"
    lzd_binary = ROOT / "subprojects" / "lzd" / "out" / "lzd"
    tdc_binary = ROOT / "subprojects" / "tudocomp" / "build" / "tdc"
    binaries = [("lzdr-comp", lzdr_binary), ("tudocomp", tdc_binary)]
    if args.stage in ("all", "performance"):
        binaries.append(("LZD", lzd_binary))
    try:
        _prepare_prerequisites(
            args.stage,
            _required_dataset_inputs(args.stage),
            binaries,
            args.prepare,
        )

        if args.stage in ("all", "counts"):
            _require_executable(lzdr_binary, "lzdr-comp")
            _require_executable(tdc_binary, "tudocomp")
            count_inputs = _factor_count_inputs()
            _require_files(path for _, path in count_inputs)

            _write_synthetic_counts(
                output_dir / "synthetic-lower-bounds.csv", lzdr_binary, args.max_k
            )
            rows = _write_factor_counts(
                output_dir / "factor-counts.csv",
                count_inputs,
                lzdr_binary,
                tdc_binary,
            )
            print("Wrote {} factor-count rows.".format(rows))

        if args.stage in ("all", "performance"):
            _require_executable(lzdr_binary, "lzdr-comp")
            _require_executable(lzd_binary, "LZD")
            _require_executable(tdc_binary, "tudocomp")
            performance_files = _performance_inputs()
            _require_files(performance_files)
            rows = _write_performance(
                output_dir / "speed-memory.csv",
                output_dir / "speed-memory.raw.json",
                performance_files,
                args.iterations,
            )
            print("Wrote {} runtime/memory rows.".format(rows))

        _write_metadata(output_dir / "metadata.json", args)
        print("Reports: {}".format(output_dir))
    except BenchmarkError as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
