FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        clang \
        cmake \
        git \
        libboost-all-dev \
        libdivsufsort-dev \
        libgoogle-glog-dev \
        libjudy-dev \
        libsdsl-dev \
        make \
        python3 \
        scons \
        valgrind \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY . /workspace

# Build the main compressor in release mode.
RUN cmake -S . -B cmake-build/release \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_TESTING=OFF \
    && cmake --build cmake-build/release --parallel "$(nproc)"

# Build the LZD subproject. These source adjustments mirror the repository's
# build-subproject-lzd recipe for its Python 3 and optimization compatibility.
RUN cd subprojects/lzd \
    && sed -i 's/\(^[ \t]*\)print \([^()]*\)$/\1print(\2)/' SConstruct \
    && sed -i 's/type(srcs) != types.ListType/not isinstance(srcs, list)/' SConstruct \
    && sed -i 's/-Ofast/-O3/' SConstruct \
    && sed -i 's/-Ofast/-O3/' src/lcacomp/Makefile \
    && scons -j"$(nproc)"

# The legacy tudocomp build recipe applies a three-commit compatibility patch.
# Create local Git metadata because the Docker context intentionally excludes
# the host repository's .git directory.
RUN set -eux; \
    cd subprojects/tudocomp; \
    git init --quiet; \
    git add -A; \
    git -c user.name=container -c user.email=container@localhost commit --quiet -m baseline; \
    git -c user.name=container -c user.email=container@localhost am ../tudocomp-fix-build.patch 2>/dev/null \
        || git am --abort; \
    sed -i -E 's/ ?-march=native//' CMakeLists.txt; \
    export CXXFLAGS="-std=gnu++14"; \
    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release; \
    cmake --build build --target tudocomp_driver --parallel "$(nproc)"

# Dataset files are mounted at runtime so the image stays reasonably sized.
# The full paper reproduction uses five timing runs and k=256 for synthetic cases.
CMD ["python3", "reproduce_paper_benchmarks.py", "--stage", "all", "--iterations", "5", "--max-k", "256"]
