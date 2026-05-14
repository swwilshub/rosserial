// rosserial2 ESP-NOW leaf publisher.
//
// Same advertise/publish program as hello_publisher, but the
// transport is ESP-NOW. The leaf unicasts to a gateway MAC compiled
// in below. No AP, no DHCP, no IP stack.

#include <cstdint>
#include <cstring>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "rosserial2/leaf_client.hpp"
#include "rosserial2/transports/espnow.hpp"

namespace {

constexpr const char* TAG = "rosserial2_leaf";

// Replace with the gateway's STA MAC (printed at boot by the gateway
// example) before flashing real hardware.
const std::uint8_t GATEWAY_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

void wifi_init() {
    esp_event_loop_create_default();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_wifi_set_storage(WIFI_STORAGE_RAM);
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_start();
}

}  // namespace

extern "C" void app_main() {
    nvs_flash_init();
    wifi_init();
    ESP_LOGI(TAG, "rosserial2 espnow_publisher booting");

    rosserial2::EspNowTransport transport{GATEWAY_MAC};
    rosserial2::LeafClient<4> client{transport};

    std::uint8_t did[rosserial2::DEVICE_ID_LEN];
    for (auto& b : did) b = static_cast<std::uint8_t>(esp_random() & 0xFF);
    std::uint8_t fh[rosserial2::FW_HASH_LEN] = {};
    client.set_identity(did, fh);

    const std::uint8_t topic = client.advertise(
        "counter", "std_msgs/msg/Int32", rosserial2::Direction::Publish);

    std::int32_t counter = 0;
    TickType_t next_publish = xTaskGetTickCount() + pdMS_TO_TICKS(1000);

    while (true) {
        const std::uint32_t now =
            static_cast<std::uint32_t>(xTaskGetTickCount() * portTICK_PERIOD_MS);
        client.poll(now);
        if (client.ready() && xTaskGetTickCount() >= next_publish) {
            const std::uint8_t payload[4] = {
                static_cast<std::uint8_t>(counter & 0xFF),
                static_cast<std::uint8_t>((counter >> 8) & 0xFF),
                static_cast<std::uint8_t>((counter >> 16) & 0xFF),
                static_cast<std::uint8_t>((counter >> 24) & 0xFF),
            };
            client.publish(topic, payload, sizeof(payload));
            ++counter;
            next_publish = xTaskGetTickCount() + pdMS_TO_TICKS(1000);
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
