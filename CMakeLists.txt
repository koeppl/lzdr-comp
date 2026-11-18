cmake_minimum_required(VERSION 3.21)
project(lzdr-comp LANGUAGES CXX)

include(CTest)

option(IWYU_ENABLED "Enable IWYU" OFF)

add_executable(
        lzdr-comp
        src/main.cpp
        src/slice.cpp
        src/slice.h
        src/compressor.cpp
        src/compressor.h
        src/radix_trie.cpp
        src/radix_trie.h
        src/lzdr_linear_time.cpp
        src/lzdr_linear_time.h
        src/std_flexible_lzdr_radix_trie.cpp
        src/std_flexible_lzdr_radix_trie.h
        src/flexible_lzdr_radix_trie.cpp
        src/flexible_lzdr_radix_trie.h
        src/flexible_lzdr_max_radix_trie.cpp
        src/flexible_lzdr_max_radix_trie.h
        src/lzd_plus_linear_time.cpp
        src/lzd_plus_linear_time.h
        src/lzd_radix_tree.cpp
        src/lzd_radix_tree.h
        src/std_flexible_lzw_naive.cpp
        src/std_flexible_lzw_naive.h
        src/flexible_lzw_naive.cpp
        src/flexible_lzw_naive.h
        src/test.cpp
        src/test.h
        src/cli.cpp
        src/cli.h
)

target_compile_features(lzdr-comp PRIVATE cxx_std_17)
set_target_properties(lzdr-comp PROPERTIES CXX_EXTENSIONS OFF)

if(MSVC)
    target_compile_options(lzdr-comp PRIVATE /W4)
    if(BUILD_TESTING)
        set_source_files_properties(src/test.cpp PROPERTIES COMPILE_OPTIONS /UNDEBUG)
    endif()
else()
    target_compile_options(lzdr-comp PRIVATE -Wall -Wextra -Wpedantic)
    if(BUILD_TESTING)
        set_source_files_properties(src/test.cpp PROPERTIES COMPILE_OPTIONS -UNDEBUG)
    endif()
endif()

if(BUILD_TESTING)
    add_test(NAME lzdr-comp-tests COMMAND lzdr-comp --test)
endif()

if(IWYU_ENABLED)
    find_program(iwyu_path NAMES include-what-you-use iwyu REQUIRED)
    set_property(TARGET lzdr-comp PROPERTY CXX_INCLUDE_WHAT_YOU_USE ${iwyu_path})
endif()
