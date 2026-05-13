// rosserial2 "hello publisher" example.
//
// Sends a HELLO, advertises an Int32 topic named ``counter``, and
// publishes a value every second. Uses UART0 (the usual USB-serial
// console on ESP32-S3 dev boards) at 921600 baud.
//
// No allocations after handshake. No exceptions. No threads beyond
// the FreeRTOS task that runs ``app_main``.

#include <cstdint>
#include <cstring>

#include "driver/uart.h"
#include "esp_log.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "rosserial2/codec.hpp"
#include "rosserial2/control.hpp"

namespace {

constexpr const char* TAG = "rosserial2_hello";

constexpr uart_port_t UART_NUM = UART_NUM_0;
constexpr int UART_TX = 1;      // adjust per board
constexpr int UART_RX = 3;      // adjust per board
constexpr int UART_BAUD = 921600;
constexpr size_t UART_RX_BUF = 1024;
constexpr size_t UART_TX_BUF = 1024;

constexpr std::uint8_t TOPIC_ID_COUNTER = 1;
constexpr const char COUNTER_NAME[] = "counter";
constexpr const char COUNTER_TYPE[] = "std_msgs/msg/Int32";

// Pre-allocated scratch buffers — no heap.
std::uint8_t g_frame_buf[rosserial2::MAX_FRAME];
std::uint8_t g_rx_buf[256];
std::uint8_t g_tx_seq = 0;

rosserial2::FrameParser g_parser;

enum class Stage : std::uint8_t {
    SendHello,
    AwaitHelloAck,
    SendAdvertise,
    AwaitAdvertiseAck,
    Publishing,
};

Stage g_stage = Stage::SendHello;

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
    uart_set_pin(UART_NUM, UART_TX, UART_RX,
                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
}

void send_frame(std::uint8_t msg_id, const std::uint8_t* payload, size_t len) {
    size_t n = 0;
    const auto s = rosserial2::encode_frame(g_tx_seq++, msg_id, payload, len,
                                            g_frame_buf, sizeof(g_frame_buf), &n);
    if (s != rosserial2::EncodeStatus::Ok) {
        ESP_LOGE(TAG, "encode failed: %u", static_cast<unsigned>(s));
        return;
    }
    uart_write_bytes(UART_NUM, reinterpret_cast<const char*>(g_frame_buf), n);
}

void send_hello() {
    rosserial2::Hello h{};
    h.proto_ver = rosserial2::PROTOCOL_VERSION;
    // device_id: pull a 16-byte random identity each boot. A
    // production firmware would use efuse / MAC. We pre-fill at init.
    for (auto& b : h.device_id) b = static_cast<std::uint8_t>(esp_random() & 0xFF);
    // fw_hash: placeholder; M5 will use the firmware image hash.
    std::memset(h.fw_hash, 0, sizeof(h.fw_hash));
    h.max_payload = rosserial2::MAX_PAYLOAD;
    std::uint8_t body[64];
    size_t n = 0;
    rosserial2::encode_hello(h, body, sizeof(body), &n);
    send_frame(rosserial2::CONTROL_MSG_ID, body, n);
}

void send_advertise() {
    std::uint8_t body[80];
    size_t n = 0;
    rosserial2::encode_advertise(
        TOPIC_ID_COUNTER, rosserial2::Direction::Publish,
        COUNTER_TYPE, static_cast<std::uint8_t>(sizeof(COUNTER_TYPE) - 1),
        COUNTER_NAME, static_cast<std::uint8_t>(sizeof(COUNTER_NAME) - 1),
        body, sizeof(body), &n);
    send_frame(rosserial2::CONTROL_MSG_ID, body, n);
}

void publish_counter(std::int32_t value) {
    std::uint8_t payload[4];
    payload[0] = static_cast<std::uint8_t>(value & 0xFF);
    payload[1] = static_cast<std::uint8_t>((value >> 8) & 0xFF);
    payload[2] = static_cast<std::uint8_t>((value >> 16) & 0xFF);
    payload[3] = static_cast<std::uint8_t>((value >> 24) & 0xFF);
    send_frame(TOPIC_ID_COUNTER, payload, sizeof(payload));
}

void on_frame(const rosserial2::DecodedView& v, void* /*user*/) {
    if (v.msg_id != rosserial2::CONTROL_MSG_ID) return;
    rosserial2::Opcode op;
    if (rosserial2::peek_opcode(v.payload, v.payload_len, &op) !=
        rosserial2::ControlStatus::Ok) {
        return;
    }
    switch (op) {
        case rosserial2::Opcode::HelloAck:
            if (g_stage == Stage::AwaitHelloAck) {
                ESP_LOGI(TAG, "HELLO_ACK received");
                g_stage = Stage::SendAdvertise;
            }
            break;
        case rosserial2::Opcode::AdvertiseAck:
            if (g_stage == Stage::AwaitAdvertiseAck) {
                rosserial2::AdvertiseAck ack{};
                rosserial2::decode_advertise_ack(v.payload + 1, v.payload_len - 1, &ack);
                if (ack.accepted) {
                    ESP_LOGI(TAG, "topic %s accepted", COUNTER_NAME);
                    g_stage = Stage::Publishing;
                } else {
                    ESP_LOGW(TAG, "topic rejected; retrying");
                    g_stage = Stage::SendAdvertise;
                }
            }
            break;
        case rosserial2::Opcode::Ping: {
            rosserial2::Ping p{};
            rosserial2::decode_ping(v.payload + 1, v.payload_len - 1, &p);
            std::uint8_t pong_body[8];
            size_t n = 0;
            rosserial2::encode_pong({p.nonce}, pong_body, sizeof(pong_body), &n);
            send_frame(rosserial2::CONTROL_MSG_ID, pong_body, n);
            break;
        }
        default:
            break;
    }
}

void pump_rx() {
    int n = uart_read_bytes(UART_NUM, g_rx_buf, sizeof(g_rx_buf), 0);
    if (n > 0) {
        g_parser.feed(g_rx_buf, static_cast<size_t>(n), on_frame, nullptr);
    }
}

}  // namespace

extern "C" void app_main() {
    uart_init();
    ESP_LOGI(TAG, "rosserial2 hello_publisher booting");

    std::int32_t counter = 0;
    TickType_t next_publish = xTaskGetTickCount() + pdMS_TO_TICKS(1000);
    TickType_t next_hello_retry = 0;

    while (true) {
        pump_rx();
        const TickType_t now = xTaskGetTickCount();

        switch (g_stage) {
            case Stage::SendHello:
                if (now >= next_hello_retry) {
                    send_hello();
                    g_stage = Stage::AwaitHelloAck;
                    next_hello_retry = now + pdMS_TO_TICKS(500);
                }
                break;
            case Stage::AwaitHelloAck:
                if (now >= next_hello_retry) {
                    g_stage = Stage::SendHello;  // resend with backoff
                }
                break;
            case Stage::SendAdvertise:
                send_advertise();
                g_stage = Stage::AwaitAdvertiseAck;
                next_hello_retry = now + pdMS_TO_TICKS(500);
                break;
            case Stage::AwaitAdvertiseAck:
                if (now >= next_hello_retry) {
                    g_stage = Stage::SendAdvertise;
                }
                break;
            case Stage::Publishing:
                if (now >= next_publish) {
                    publish_counter(counter++);
                    next_publish = now + pdMS_TO_TICKS(1000);
                }
                break;
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
