cmake_minimum_required(VERSION 3.20)

# Point ESP-IDF at the shared component tree one level up.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(rosserial2_hello_publisher)
