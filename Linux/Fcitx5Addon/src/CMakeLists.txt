# Engine source directory
set(ENGINE_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../Source/Engine")

# Pre-built engine static libraries
set(MCBOPOMOFOLM_LIB "${ENGINE_SRC_DIR}/build/libMcBopomofoLMLib.a")
set(GRAMAMBULAR2_LIB "${ENGINE_SRC_DIR}/build/gramambular2/libgramambular2_lib.a")
set(MANDARIN_LIB "${ENGINE_SRC_DIR}/build/Mandarin/libMandarinLib.a")

# Engine parent directory (Source/) for includes like Engine/McBopomofoLM.h
get_filename_component(ENGINE_PARENT_DIR "${ENGINE_SRC_DIR}" DIRECTORY)

# Add the addon as a MODULE library (shared library for Fcitx5)
add_library(mcbopomofo MODULE
    McBopomofoEngine.h
    McBopomofoEngine.cpp
)

# Include directories
target_include_directories(mcbopomofo PRIVATE
    "${ENGINE_PARENT_DIR}"                 # for Engine/McBopomofoLM.h etc.
    "${ENGINE_SRC_DIR}/gramambular2"       # for reading_grid.h (direct include)
    "${ENGINE_SRC_DIR}/Mandarin"           # for Mandarin.h (direct include)
    ${Fcitx5Core_INCLUDE_DIRS}
)

# Link libraries
target_link_libraries(mcbopomofo PRIVATE
    "${MCBOPOMOFOLM_LIB}"
    "${GRAMAMBULAR2_LIB}"
    "${MANDARIN_LIB}"
    Fcitx5::Core
    pthread
    dl
)

# Pass Fcitx5 install prefix for default data path resolution.
# On Ubuntu 22.04 this is /usr; CMAKE_INSTALL_PREFIX defaults to /usr/local.
target_compile_definitions(mcbopomofo PRIVATE
    FCITX5_INSTALL_PREFIX="${CMAKE_INSTALL_PREFIX}"
)

# Set output name without "lib" prefix on Linux (Fcitx5 expects mcbopomofo.so)
set_target_properties(mcbopomofo PROPERTIES
    OUTPUT_NAME "mcbopomofo"
    PREFIX ""
    SUFFIX ".so"
)

# Install the addon shared library
install(TARGETS mcbopomofo
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}/fcitx5"
)

# Configure and install addon registration file
configure_file(mcbopomofo-addon.conf.in mcbopomofo-addon.conf @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/mcbopomofo-addon.conf
    DESTINATION "${CMAKE_INSTALL_DATADIR}/fcitx5/addon"
)

# Configure and install input method registration file
configure_file(mcbopomofo.conf.in mcbopomofo.conf @ONLY)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/mcbopomofo.conf
    DESTINATION "${CMAKE_INSTALL_DATADIR}/fcitx5/inputmethod"
)

# Install dictionary data
set(DATA_TXT_PATH "${CMAKE_CURRENT_SOURCE_DIR}/../../../Source/Data/data.txt")
if(EXISTS "${DATA_TXT_PATH}")
    install(FILES "${DATA_TXT_PATH}"
        DESTINATION "${CMAKE_INSTALL_DATADIR}/fcitx5/mcbopomofo"
    )
endif()