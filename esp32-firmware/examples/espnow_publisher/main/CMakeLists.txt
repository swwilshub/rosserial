idf_component_register(
    SRCS "espnow_publisher.cpp"
    INCLUDE_DIRS ""
    REQUIRES rosserial2_codec esp_wifi esp_event nvs_flash esp_netif
)
