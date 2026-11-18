# lzdr-comp

Warning: only tested on Linux.

## Dependencies
### Build Dependencies
* For lzdr-comp: CMake 3.21+ and a C++17 compiler
* For lzd: SCons, clang
* For [tudocomp](https://tudocomp.github.io/documentation/index.html#building): CMake, Make, Python 3

### Justfile Dependencies
* Basic dependencies: just, git, jq, wget (just is optional if using CMake directly)
* Additional dev dependencies: include-what-you-use, tokei

### Dependency Installation

- Arch Linux: `pacman -S cmake gcc python git jq wget just scons clang valgrind`

## Usage
### Build lzdr-comp
Release mode:
```
just build-release
```

Or configure and build directly with CMake:
```
cmake --preset release
cmake --build --preset release --parallel
```

Debug mode:
```
just build-debug
```

Executables are located at `cmake-build/release/lzdr-comp` and `cmake-build/debug/lzdr-comp` after the build process.
Run the test suite with `ctest --preset debug` (or `just test`). The presets also include `relwithdebinfo`.

- The executables expect input to parse from `<STDIN>`
- To compute the number of factors of all implemented algorithms, run one of the executables with parameter `--factors`
- To restrict the computation to LZD+/LZDR, run with `-a [lzd+|lzdr]` (you need to write lzd or lzd+ in lower case)
- The Debug executable also outputs verbosely the constructed factors

### Build subprojects
Build lzd and tudocomp:
```
just build-subprojects
```

### Download Pizza&Chili dataset
```
just download-pizza-chili-dataset
```
Saved into `datasets` directory.

### Factor count comparison
```
just factor-count <FILE>
```

### Calgary and Canterbury factor counts
```
just factor-count-ca-bench
```

### Pizza&Chili factor counts
```
just factor-count-pizza-chili-bench
```

### Execution time and maximum memory usage
Use `bench_speed_mem.py`. Requires Python 3 and Valgrind.
