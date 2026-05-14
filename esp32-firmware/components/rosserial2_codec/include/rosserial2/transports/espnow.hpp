// ESP-NOW transport for firmware leaves and gateways.
//
// The leaf transport unicasts to a single peer (the gateway MAC);
// the gateway transport sends to whatever leaf MAC was last heard
// from. Both wrap the same FreeRTOS ring buffer for received bytes.
//
// Header-only and gated on the ESP-IDF wifi/espnow headers, so the
// codec component still compiles cleanly on the host target.

#pragma once

#if __has_include("esp_now.h")
#define ROSSERIAL2_HAS_ESPNOW 1
#include "esp_now.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/ringbuf.h"
#endif

#include <cstddef>
#include <cstdint>
#include <cstring>

#include "rosserial2/transport.hpp"

namespace rosserial2 {

inline constexpr std::size_t ESPNOW_MAX_FRAME = 250;

#ifdef ROSSERIAL2_HAS_ESPNOW

class EspNowTransport final : public Transport {
public:
    /// ``peer_mac`` is the destination MAC for unicasts. If null,
    /// frames are broadcast (FF:FF:FF:FF:FF:FF).
    explicit EspNowTransport(const std::uint8_t* peer_mac = nullptr) noexcept {
        instance_ = this;
        if (peer_mac != nullptr) {
            std::memcpy(peer_mac_, peer_mac, 6);
            peer_set_ = true;
        } else {
            std::memset(peer_mac_, 0xFF, 6);
            peer_set_ = true;
        }
        rb_ = xRingbufferCreate(2048, RINGBUF_TYPE_BYTEBUF);
        esp_now_init();
        esp_now_register_recv_cb(&EspNowTransport::recv_cb_);
        esp_now_peer_info_t peer = {};
        std::memcpy(peer.peer_addr, peer_mac_, 6);
        peer.channel = 0;
        peer.ifidx = WIFI_IF_STA;
        peer.encrypt = false;
        esp_now_add_peer(&peer);
    }

    std::size_t read(std::uint8_t* buf, std::size_t cap) noexcept override {
        if (rb_ == nullptr) return ErrorSentinel;
        std::size_t got_total = 0;
        while (got_total < cap) {
            std::size_t got = 0;
            void* item = xRingbufferReceiveUpTo(rb_, &got, 0, cap - got_total);
            if (item == nullptr) break;
            std::memcpy(buf + got_total, item, got);
            vRingbufferReturnItem(rb_, item);
            got_total += got;
        }
        return got_total;
    }

    bool write(const std::uint8_t* data, std::size_t len) noexcept override {
        // ESP-NOW max payload is 250 bytes per packet. Chunk if the
        // caller hands us more (which only happens if a tx-side frame
        // is larger than 250B — our MAX_PAYLOAD config keeps it below
        // that, but we chunk defensively).
        std::size_t off = 0;
        while (off < len) {
            const std::size_t take = (len - off) > ESPNOW_MAX_FRAME ? ESPNOW_MAX_FRAME : (len - off);
            if (esp_now_send(peer_mac_, data + off, take) != ESP_OK) return false;
            off += take;
        }
        return true;
    }

    const char* name() const noexcept override { return "espnow"; }

    void update_peer(const std::uint8_t* mac) noexcept {
        std::memcpy(peer_mac_, mac, 6);
        esp_now_peer_info_t peer = {};
        std::memcpy(peer.peer_addr, peer_mac_, 6);
        peer.channel = 0;
        peer.ifidx = WIFI_IF_STA;
        peer.encrypt = false;
        esp_now_del_peer(peer_mac_);
        esp_now_add_peer(&peer);
    }

private:
    static EspNowTransport* instance_;
    RingbufHandle_t rb_ = nullptr;
    std::uint8_t peer_mac_[6] = {};
    bool peer_set_ = false;

    static void recv_cb_(const esp_now_recv_info_t* info,
                         const std::uint8_t* data, int len) noexcept {
        auto* self = instance_;
        if (self == nullptr || self->rb_ == nullptr) return;
        // Remember the last sender as the new peer for gateway role.
        std::memcpy(self->peer_mac_, info->src_addr, 6);
        xRingbufferSend(self->rb_, data, len, 0);
    }
};

inline EspNowTransport* EspNowTransport::instance_ = nullptr;

#endif  // ROSSERIAL2_HAS_ESPNOW

}  // namespace rosserial2
