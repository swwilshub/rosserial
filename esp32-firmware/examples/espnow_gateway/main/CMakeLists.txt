idf_component_register(
    SRCS "espnow_gateway.cpp"
    INCLUDE_DIRS ""
    REQUIRES rosserial2_codec driver esp_wifi esp_event nvs_flash esp_netif
)
