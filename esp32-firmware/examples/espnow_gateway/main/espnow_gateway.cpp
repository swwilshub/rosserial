// rosserial2 ESP-NOW gateway.
//
// USB-connected ESP32 that bridges between ESP-NOW (towards leaves)
// and UART (towards the host bridge). It does not parse the wire
// format — it forwards bytes both directions. ADR-0011.

#include <cstdint>
#include <cstring>

#include "driver/uart.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "rosserial2/transports/espnow.hpp"

namespace {

constexpr const char* TAG = "rosserial2_gateway";

constexpr uart_port_t UART_NUM = UART_NUM_0;
constexpr int UART_BAUD = 921600;
constexpr int UART_RX_BUF = 2048;
constexpr int UART_TX_BUF = 2048;

void uart_init() {
    uart_config_t cfg = {};
    cfg.baud_rate = UART_BAUD;
    cfg.data_bits = UART_DATA_8_BITS;
    cfg.parity = UART_PARITY_DISABLE;
    cfg.stop_bits = UART_STOP_BITS_1;
    cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;
    uart_driver_install(UART_NUM, UART_RX_BUF, UART_TX_BUF, 0, nullptr, 0);
    uart_param_config(UART_NUM, &cfg);
}

void wifi_init() {
    esp_event_loop_create_default();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_wifi_set_storage(WIFI_STORAGE_RAM);
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_start();
}

void log_mac() {
    std::uint8_t mac[6];
    esp_wifi_get_mac(WIFI_IF_STA, mac);
    ESP_LOGI(TAG, "gateway STA MAC: %02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

}  // namespace

extern "C" void app_main() {
    nvs_flash_init();
    uart_init();
    wifi_init();
    log_mac();
    ESP_LOGI(TAG, "rosserial2 espnow_gateway booting");

    // Broadcast on init; the transport updates its peer to the last
    // sender when leaves transmit.
    rosserial2::EspNowTransport espnow{nullptr};

    std::uint8_t buf[256];
    while (true) {
        // ESP-NOW → UART: forward decoded bytes the transport collected
        // from any leaf.
        const std::size_t got = espnow.read(buf, sizeof(buf));
        if (got > 0 && got != rosserial2::Transport::ErrorSentinel) {
            uart_write_bytes(UART_NUM, reinterpret_cast<const char*>(buf), got);
        }
        // UART → ESP-NOW: forward bytes from the host bridge to the
        // current peer. esp_now_send caps at 250 bytes per packet;
        // the transport chunks internally.
        const int n = uart_read_bytes(UART_NUM, buf, sizeof(buf), 0);
        if (n > 0) {
            espnow.write(buf, static_cast<std::size_t>(n));
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}
