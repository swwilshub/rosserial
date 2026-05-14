// UART transport for firmware. Trivial wrapper over the ESP-IDF
// uart_driver, conforming to rosserial2::Transport.
//
// Header-only so the codec component stays sourceless. The
// ESP-IDF symbols are referenced via #include only inside the .cpp
// of the example that uses this transport, but for convenience we
// gate the entire class on __has_include("driver/uart.h") so it
// compiles cleanly on the host (where it is simply unavailable).

#pragma once

#if __has_include("driver/uart.h")
#define ROSSERIAL2_HAS_UART 1
#include "driver/uart.h"
#endif

#include <cstddef>
#include <cstdint>

#include "rosserial2/transport.hpp"

namespace rosserial2 {

#ifdef ROSSERIAL2_HAS_UART

class UartTransport final : public Transport {
public:
    UartTransport(uart_port_t port,
                  int baud,
                  int tx_pin,
                  int rx_pin,
                  std::size_t rx_buf = 1024,
                  std::size_t tx_buf = 1024) noexcept
        : port_(port) {
        uart_config_t cfg = {};
        cfg.baud_rate = baud;
        cfg.data_bits = UART_DATA_8_BITS;
        cfg.parity = UART_PARITY_DISABLE;
        cfg.stop_bits = UART_STOP_BITS_1;
        cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
        cfg.source_clk = UART_SCLK_DEFAULT;
        uart_driver_install(port_, rx_buf, tx_buf, 0, nullptr, 0);
        uart_param_config(port_, &cfg);
        uart_set_pin(port_, tx_pin, rx_pin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    }

    std::size_t read(std::uint8_t* buf, std::size_t cap) noexcept override {
        const int n = uart_read_bytes(port_, buf, cap, 0);
        return n < 0 ? ErrorSentinel : static_cast<std::size_t>(n);
    }

    bool write(const std::uint8_t* data, std::size_t len) noexcept override {
        const int n = uart_write_bytes(port_, reinterpret_cast<const char*>(data), len);
        return n == static_cast<int>(len);
    }

    const char* name() const noexcept override { return "uart"; }

private:
    uart_port_t port_;
};

#endif  // ROSSERIAL2_HAS_UART

}  // namespace rosserial2
