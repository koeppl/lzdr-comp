set positional-arguments
set ignore-comments

[private]
default:
  @just --list --unsorted

[group('lzdr-comp')]
build-debug:
  @cmake --preset debug && cmake --build --preset debug --parallel

[group('lzdr-comp')]
build-release:
  @cmake --preset release && cmake --build --preset release --parallel

[group('lzdr-comp')]
build-relwithdebinfo:
  @cmake --preset relwithdebinfo && cmake --build --preset relwithdebinfo --parallel

[group('lzdr-comp')]
build-release-debug:
  @just build-relwithdebinfo

[group('lzdr-comp')]
run-debug *ARGS: build-debug
  @./cmake-build/debug/lzdr-comp "$@"

[group('lzdr-comp')]
run-release *ARGS: build-release
  @./cmake-build/release/lzdr-comp "$@"

[group('lzdr-comp')]
run-release-debug *ARGS: build-release-debug
  @./cmake-build/relwithdebinfo/lzdr-comp "$@"

[group('lzdr-comp')]
clean:
  @rm -rf cmake-build/ target/

[group('lzdr-comp-dev')]
test: build-debug
  @ctest --preset debug

[group('lzdr-comp-dev')]
iwyu:
  @cmake -S . -B cmake-build/iwyu -DCMAKE_BUILD_TYPE=Debug -DIWYU_ENABLED=ON && cmake --build cmake-build/iwyu --parallel

[group('lzdr-comp-dev')]
loc:
  @tokei -t='C++,C Header' -f src/ -s files

[group('subprojects')]
[private]
init-subprojects:
  @git submodule update --init --recursive || true

[group('subprojects')]
build-subprojects: build-subproject-lzd build-subproject-tudocomp

[group('subprojects')]
build-subproject-lzd: init-subprojects
  # Replace -Ofast with -O3 to make benchmark more comparable
  @cd subprojects/lzd/ && sed -i 's/\(^[ \t]*\)print \([^()]*\)$/\1print(\2)/' SConstruct && sed -i 's/type(srcs) != types.ListType/not isinstance(srcs, list)/' SConstruct && sed -i 's/-Ofast/-O3/' SConstruct && sed -i 's/-Ofast/-O3/' src/lcacomp/Makefile && scons

[group('subprojects')]
build-subproject-tudocomp: init-subprojects
  #!/usr/bin/env bash
  set -euo pipefail
  cd subprojects/tudocomp/
  ret=0
  git -c user.name='localhost' -c user.email='<>' am ../tudocomp-fix-build.patch 2> /dev/null || ret=$?
  if [ "$ret" -ne 0 ]; then
    git -c user.name='localhost' -c user.email='<>' am --abort
  fi
  sed -i -E 's/ ?-march=native//' CMakeLists.txt # Replace march=native to make benchmark more comparable
  mkdir -p build/ && cd build/
  export CXXFLAGS="-std=gnu++14"
  cmake -S .. -B . -DCMAKE_BUILD_TYPE=Release
  cmake --build . --parallel

[group('subprojects')]
clean-subprojects:
  @rm -rf subprojects/lzd/out/ subprojects/tudocomp/build/

[group('datasets')]
download-pizza-chili-dataset:
  #!/usr/bin/env bash
  set -euo pipefail
  mkdir -p datasets/pizza-chili/
  cd datasets/pizza-chili/
  mkdir -p sources
  cd sources
  wget 'https://pizzachili.dcc.uchile.cl/texts/code/sources.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/code/sources.50MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/code/sources.100MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/code/sources.200MB.gz'
  cd ..
  mkdir -p pitches
  cd pitches
  wget 'https://pizzachili.dcc.uchile.cl/texts/music/pitches.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/music/pitches.50MB.gz'
  cd ..
  mkdir -p proteins
  cd proteins
  wget 'https://pizzachili.dcc.uchile.cl/texts/protein/proteins.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/protein/proteins.50MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/protein/proteins.100MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/protein/proteins.200MB.gz'
  cd ..
  mkdir -p dna
  cd dna
  wget 'https://pizzachili.dcc.uchile.cl/texts/dna/dna.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/dna/dna.50MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/dna/dna.100MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/dna/dna.200MB.gz'
  cd ..
  mkdir -p english
  cd english
  wget 'https://pizzachili.dcc.uchile.cl/texts/nlang/english.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/nlang/english.50MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/nlang/english.100MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/nlang/english.200MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/nlang/english.1024MB.gz'
  cd ..
  mkdir -p xml
  cd xml
  wget 'https://pizzachili.dcc.uchile.cl/texts/xml/dblp.xml.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/xml/dblp.xml.50MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/xml/dblp.xml.100MB.gz'
  wget 'https://pizzachili.dcc.uchile.cl/texts/xml/dblp.xml.200MB.gz'
  cd ..
  gunzip $(find . -mindepth 2 -type f -name '*.gz')

[group('all')]
factor-count FILE:
  @if [ ! -f cmake-build/release/lzdr-comp ]; then just build-release; fi
  @if [ ! -f subprojects/lzd/out/lzd ]; then just build-subproject-lzd; fi
  @if [ ! -f subprojects/tudocomp/build/tdc ]; then just build-subproject-tudocomp; fi
  @echo lzdr-comp
  @./cmake-build/release/lzdr-comp --factors -c < "$1" | sed 's/^/  /'
  @echo
  @echo tudocomp
  @echo '  LZ78'
  @./subprojects/tudocomp/build/tdc -a 'lz78(coder=ascii)' -s --raw -f -o /dev/null -- "$1" | jq -r '.data.sub[0].stats[] | select(.key == "factor_count").value' | sed 's/^/  Num factors: /'
  @echo
  @echo '  LZW'
  @./subprojects/tudocomp/build/tdc -a 'lzw(coder=ascii)' -s --raw -f -o /dev/null -- "$1" | jq -r '.data.sub[0].stats[] | select(.key == "factor_count").value' | sed 's/^/  Num factors: /'

[group('all')]
factor-count-ca-bench:
  #!/usr/bin/env bash
  set -euo pipefail
  dir=$(mktemp -d)
  trap "rm -rf $dir" EXIT
  mkdir -p "$dir"/canterbury "$dir"/calgary
  cp -f -t "$dir"/canterbury datasets/canterbury/*
  cp -f -t "$dir"/calgary datasets/calgary/*
  chmod 644 "$dir"/canterbury/* "$dir"/calgary/*
  first_iter=1
  for f in "$dir"/canterbury/* "$dir"/calgary/*; do
    if [ "$first_iter" -ne 1 ]; then echo; fi
    echo "$f ($(du -h "$f" | awk '{ print $1 }'))"
    just factor-count "$f"
    first_iter=0
  done

[group('all')]
factor-count-pizza-chili-bench:
  #!/usr/bin/env bash
  set -euo pipefail
  chmod -R 755 datasets/pizza-chili/
  first_iter=1
  for f in $(find datasets/pizza-chili/ -mindepth 2 -type f); do
    file_size=$(du -m "$f" | cut -f1)
    if [ "$file_size" -le 250 ]; then
      if [ "$first_iter" -ne 1 ]; then echo; fi
      echo "$f ($(du -h "$f" | awk '{ print $1 }'))"
      just factor-count "$f"
      first_iter=0
    fi
  done
