cmake_minimum_required(VERSION 3.16)
project(fcitx5-mcbopomofo VERSION 0.1.0 LANGUAGES CXX)

# Find Extra CMake Modules (ECM)
find_package(ECM REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} ${ECM_MODULE_PATH})

# Find Fcitx5Core 5.0.14
find_package(Fcitx5Core 5.0.14 REQUIRED)

# C++17 standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Engine source directory
set(ENGINE_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../Source/Engine")

# Pre-built engine static libraries
set(MCBOPOMOFOLM_LIB "${ENGINE_SRC_DIR}/build/libMcBopomofoLMLib.a")
set(GRAMAMBULAR2_LIB "${ENGINE_SRC_DIR}/build/gramambular2/libgramambular2_lib.a")
set(MANDARIN_LIB "${ENGINE_SRC_DIR}/build/Mandarin/libMandarinLib.a")

# Verify pre-built libs exist
if(NOT EXISTS "${MCBOPOMOFOLM_LIB}")
    message(FATAL_ERROR "Pre-built engine library not found: ${MCBOPOMOFOLM_LIB}. Build the engine first: cd Source/Engine && mkdir -p build && cd build && cmake -DENABLE_TEST=ON .. && make")
endif()

if(NOT EXISTS "${GRAMAMBULAR2_LIB}")
    message(FATAL_ERROR "Pre-built gramambular2 library not found: ${GRAMAMBULAR2_LIB}")
endif()

if(NOT EXISTS "${MANDARIN_LIB}")
    message(FATAL_ERROR "Pre-built Mandarin library not found: ${MANDARIN_LIB}")
endif()

# Include standard ECM modules
include(ECMUninstallTarget)
include(GNUInstallDirs)
include(FeatureSummary)

add_subdirectory(src)