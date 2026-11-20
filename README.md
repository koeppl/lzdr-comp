# lzdr-comp

`lzdr-comp` is a C++17 command-line program for computing factor counts with
LZDR and related LZD, LZW, and flexible variants. It reads the input byte stream
from standard input.

> **Platform support:** Linux is the only tested platform.

## Requirements

To build `lzdr-comp`, install:

- CMake 3.21 or newer
- A C++17 compiler
- A build tool supported by CMake, such as Make or Ninja

The `just` command is optional. It provides shortcuts for common build,
test, and benchmark tasks. Subproject builds and optional workflows have
additional requirements described below.

## Build

From the repository root, configure and build the Release executable:

```sh
cmake --preset release
cmake --build --preset release --parallel
```

The executable is written to `cmake-build/release/lzdr-comp`. To build the
Debug version, use the `debug` preset instead:

```sh
cmake --preset debug
cmake --build --preset debug --parallel
```

The available presets are `debug`, `release`, and `relwithdebinfo`. If you have
`just` installed, the equivalent shortcuts are `just build-debug`,
`just build-release`, and `just build-relwithdebinfo`.

## Run

The program reads bytes from standard input. For example, count factors for a
file using all implemented algorithms:

```sh
./cmake-build/release/lzdr-comp --factors < input.txt
```

Run one supported algorithm at a time with `-a`:

```sh
./cmake-build/release/lzdr-comp -a lzdr < input.txt
./cmake-build/release/lzdr-comp -a 'lzd+' < input.txt
```

Use `--help` to print the command-line options. The main options are:

| Option | Description |
| --- | --- |
| `--factors` | Print factor counts for all implemented algorithms. |
| `-a ALGORITHM` | Run one scheme (`lzdr`, `lzdr-std-flex`, `lzdr-alt-flex`, `lzdr-max-alt`, `lzd+`, `lzd`, `lzw-std-flex`, or `lzw-alt-flex`). |
| `-c` | Check that decompression reproduces the input for algorithms that support this check. |
| `--test` | Run the built-in tests. Prefer CTest as shown below. |

The decompression check is unavailable for the LZW variants and Alternative
Flexible LZDR Max.

## Test

Configure and build the Debug preset, then run the test suite through CTest:

```sh
cmake --preset debug
cmake --build --preset debug --parallel
ctest --preset debug
```

CTest is also configured for the Release and RelWithDebInfo presets. With
`just` installed, `just test` builds Debug and runs its CTest suite.

## Optional workflows

### Build comparison subprojects

The LZD and tudocomp comparison tools are optional. Their builds require Git,
SCons, Clang, CMake, Python 3, a CMake-compatible build tool, and the
dependencies listed in [tudocomp's build documentation](https://tudocomp.github.io/documentation/index.html#building).
Initialize and build them with:

```sh
just build-subprojects
```

### Compare factor counts

Compare an input file with the tudocomp implementations:

```sh
just factor-count path/to/input.txt
```

For Calgary and Canterbury datasets, run:

```sh
just factor-count-ca-bench
```

This expects the files in `datasets/calgary/` and `datasets/canterbury/`.

To download the Pizza & Chili datasets and run their factor-count comparison:

```sh
just download-pizza-chili-dataset
just factor-count-pizza-chili-bench
```

The download requires `wget`; the comparison considers files up to 250 MiB.
The comparison recipes use `jq` to read tudocomp's output.

### Measure speed and memory

`bench_speed_mem.py` compares the compressor implementations for one or more
input files. Build the Release executable and comparison subprojects first with
`just build-release` and `just build-subprojects`. The script requires Python
3; install Valgrind to collect memory measurements. Run
`python3 bench_speed_mem.py --help` for its options.

### Reproduce the paper benchmarks with Docker

Initialize the Git submodules, then build the Docker image from the repository
root:

```sh
git submodule update --init --recursive
docker build -t lzdr-paper-benchmarks .
```

The container runs the synthetic lower-bound cases, practical factor-count
tables, and Pizza&Chili runtime/peak-memory measurements. The script prepares
missing build outputs and downloads missing benchmark files from the
[Canterbury](https://corpus.canterbury.ac.nz/descriptions/) and
[Pizza&Chili](https://pizzachili.dcc.uchile.cl/texts.html) corpus sites. These
downloads total about 1.8 GiB of uncompressed Pizza&Chili prefixes, plus the
small Calgary and Canterbury archives. The script does not install system
packages; install the dependencies listed in the Dockerfile first. Mount the
dataset tree writable so preparation can save downloads, along with a results
directory:

```sh
mkdir -p benchmark-results
docker run --rm \
  -v "$PWD/datasets:/workspace/datasets" \
  -v "$PWD/benchmark-results:/workspace/benchmark-results" \
  lzdr-paper-benchmarks
```

Reports are written as CSV and JSON files in `benchmark-results/`. Runtime uses
the paper's median of five runs; peak memory uses Valgrind Massif.

The factor-count report marks Alternative Flexible LZDR on the 100 and 200 MiB
XML inputs as `paper_n/a_timeout`, matching the paper's entries that did not
finish within several hours. Run the script directly to select a stage or
change the iteration count:

```sh
python3 reproduce_paper_benchmarks.py --help
```

Pass `--no-prepare` to skip automatic builds and downloads. The script still
checks for missing prerequisites and reports them before running.

To run it directly from the repository root:

```sh
python3 reproduce_paper_benchmarks.py
```
