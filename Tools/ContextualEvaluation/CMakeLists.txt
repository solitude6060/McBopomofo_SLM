cmake_minimum_required(VERSION 3.12)
project(McBopomofoEvaluator)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Engine source tree (for headers)
set(ENGINE_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../Source/Engine")

# Pre-built static libraries
set(ENGINE_BUILD_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../Source/Engine/build")
set(MCBOPOMOFOLM_LIB "${ENGINE_BUILD_DIR}/libMcBopomofoLMLib.a")
set(GRAMAMBULAR2_LIB "${ENGINE_BUILD_DIR}/gramambular2/libgramambular2_lib.a")
set(MANDARIN_LIB "${ENGINE_BUILD_DIR}/Mandarin/libMandarinLib.a")

# Verify pre-built libs exist
if(NOT EXISTS "${MCBOPOMOFOLM_LIB}")
    message(FATAL_ERROR "Pre-built engine library not found: ${MCBOPOMOFOLM_LIB}. Build the engine first: cd Source/Engine && mkdir -p build && cd build && cmake -DENABLE_TEST=ON .. && make")
endif()

add_executable(evaluator evaluator.cpp)

# evaluator.cpp uses "Engine/..." and "Engine/gramambular2/..." includes,
# so we add the directory above Engine/ (i.e. Source/) as an include root.
get_filename_component(ENGINE_PARENT_DIR "${ENGINE_SRC_DIR}" DIRECTORY)
target_include_directories(evaluator PRIVATE
    "${ENGINE_PARENT_DIR}"              # for Engine/McBopomofoLM.h etc.
    "${ENGINE_SRC_DIR}/gramambular2"    # for reading_grid.h (direct include)
    "${ENGINE_SRC_DIR}/Mandarin"        # for Mandarin.h (direct include)
)

target_link_libraries(evaluator PRIVATE
    "${MCBOPOMOFOLM_LIB}"
    "${GRAMAMBULAR2_LIB}"
    "${MANDARIN_LIB}"
    pthread
    dl
)

# Expose data.txt path as a cache variable for convenience
set(DATA_TXT_PATH "${CMAKE_CURRENT_SOURCE_DIR}/../../Source/Data/data.txt"
    CACHE FILEPATH "Path to language model data.txt")
message(STATUS "Evaluator data.txt: ${DATA_TXT_PATH}")
