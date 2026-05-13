# ESP-IDF component manifest for the rosserial2 codec.
#
# Header-only; the include directory is exposed to dependents. No
# sources are compiled by IDF itself for this component. The host_test
# CMake build (esp32-firmware/host_test) consumes the same headers via
# a separate target.

idf_component_register(
    INCLUDE_DIRS include
)
