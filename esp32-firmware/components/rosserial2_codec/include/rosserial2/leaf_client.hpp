// LeafClient — device-side rosserial2 session state machine.
//
// Wraps a Transport + FrameParser + a small advertise/publish API.
// Host-testable: pass a fake Transport and a fake clock. No
// allocations after construction.
//
// Usage on device:
//
//     UartTransport uart{...};
//     LeafClient<8 /*max topics*/> client{uart};
//     client.set_identity(device_id, fw_hash);
//     std::uint8_t TOPIC_COUNTER = client.advertise(
//         "counter", "std_msgs/msg/Int32",
//         rosserial2::Direction::Publish);
//     while (true) {
//         client.poll(now_ms);
//         if (client.ready()) client.publish(TOPIC_COUNTER, payload, len);
//         vTaskDelay(...);
//     }
//
// The state machine drives HELLO → AwaitHelloAck → (Advertise each
// pending) → Ready, with exponential-backoff retries on each step.
// PINGs from the bridge are answered automatically.

#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

#include "rosserial2/codec.hpp"
#include "rosserial2/control.hpp"
#include "rosserial2/transport.hpp"

namespace rosserial2 {

enum class LeafState : std::uint8_t {
    SendHello,
    AwaitHelloAck,
    Advertise,
    AwaitAdvertiseAck,
    Ready,
    Closed,
};

template <std::size_t MaxTopics = 8>
class LeafClient {
public:
    struct TopicSlot {
        bool used = false;
        bool acked = false;
        std::uint8_t topic_id = 0;
        Direction direction = Direction::Publish;
        char name[40] = {};
        std::uint8_t name_len = 0;
        char type_str[64] = {};
        std::uint8_t type_len = 0;
        // Callback when a SUBSCRIBE payload arrives from the bridge.
        // Pointer-to-function + opaque user pointer. nullptr ⇒ ignore.
        void (*on_payload)(const std::uint8_t* data, std::size_t len, void* user) = nullptr;
        void* on_payload_user = nullptr;
    };

    explicit LeafClient(Transport& transport,
                        std::uint32_t hello_retry_ms = 500) noexcept
        : transport_(transport), hello_retry_ms_(hello_retry_ms) {}

    void set_identity(const std::uint8_t* device_id, const std::uint8_t* fw_hash) noexcept {
        std::memcpy(device_id_, device_id, DEVICE_ID_LEN);
        std::memcpy(fw_hash_, fw_hash, FW_HASH_LEN);
    }

    /// Returns the assigned topic id, or 0 if the table is full.
    std::uint8_t advertise(const char* name,
                           const char* type_str,
                           Direction direction,
                           void (*on_payload)(const std::uint8_t*, std::size_t, void*) = nullptr,
                           void* user = nullptr) noexcept {
        if (next_topic_id_ == 0) next_topic_id_ = 1;
        for (auto& s : topics_) {
            if (!s.used) {
                s.used = true;
                s.acked = false;
                s.topic_id = next_topic_id_++;
                if (next_topic_id_ == 0) next_topic_id_ = 1;
                s.direction = direction;
                s.name_len = static_cast<std::uint8_t>(strnlen_(name, sizeof(s.name)));
                std::memcpy(s.name, name, s.name_len);
                s.type_len = static_cast<std::uint8_t>(strnlen_(type_str, sizeof(s.type_str)));
                std::memcpy(s.type_str, type_str, s.type_len);
                s.on_payload = on_payload;
                s.on_payload_user = user;
                // Force re-advertise pass on next poll if we were Ready.
                if (state_ == LeafState::Ready) state_ = LeafState::Advertise;
                return s.topic_id;
            }
        }
        return 0;
    }

    /// Publish raw payload bytes on a topic_id obtained from advertise().
    /// No-op if the topic isn't ACKed yet.
    bool publish(std::uint8_t topic_id, const std::uint8_t* data, std::size_t len) noexcept {
        if (state_ != LeafState::Ready) return false;
        auto* s = find_(topic_id);
        if (s == nullptr || !s->acked || s->direction != Direction::Publish) return false;
        return send_(topic_id, data, len);
    }

    bool ready() const noexcept { return state_ == LeafState::Ready; }
    LeafState state() const noexcept { return state_; }

    /// Drive the state machine. ``now_ms`` is a free-running monotonic
    /// counter; only relative deltas matter.
    void poll(std::uint32_t now_ms) noexcept {
        pump_rx_();
        switch (state_) {
            case LeafState::SendHello:
                if (now_ms - last_action_ms_ >= hello_retry_ms_ || last_action_ms_ == 0) {
                    send_hello_();
                    last_action_ms_ = now_ms;
                    state_ = LeafState::AwaitHelloAck;
                }
                break;
            case LeafState::AwaitHelloAck:
                if (now_ms - last_action_ms_ >= hello_retry_ms_) {
                    state_ = LeafState::SendHello;
                }
                break;
            case LeafState::Advertise: {
                TopicSlot* pending = next_pending_();
                if (pending == nullptr) {
                    state_ = LeafState::Ready;
                    break;
                }
                send_advertise_(*pending);
                last_action_ms_ = now_ms;
                pending_advertise_ = pending->topic_id;
                state_ = LeafState::AwaitAdvertiseAck;
                break;
            }
            case LeafState::AwaitAdvertiseAck:
                if (now_ms - last_action_ms_ >= hello_retry_ms_) {
                    state_ = LeafState::Advertise;  // resend
                }
                break;
            case LeafState::Ready:
            case LeafState::Closed:
                break;
        }
    }

    // --- counters (for tests) -----------------------------------------
    std::size_t bytes_in() const noexcept { return bytes_in_; }
    std::size_t bytes_out() const noexcept { return bytes_out_; }
    std::size_t frames_in() const noexcept { return frames_in_; }
    std::size_t frames_out() const noexcept { return frames_out_; }

    /// Iterate topics for inspection in tests.
    const TopicSlot& topic(std::size_t i) const noexcept { return topics_[i]; }

private:
    Transport& transport_;
    std::uint32_t hello_retry_ms_;
    LeafState state_ = LeafState::SendHello;
    std::uint32_t last_action_ms_ = 0;
    std::uint8_t pending_advertise_ = 0;
    std::uint8_t tx_seq_ = 0;
    std::uint8_t next_topic_id_ = 1;
    std::uint8_t device_id_[DEVICE_ID_LEN] = {};
    std::uint8_t fw_hash_[FW_HASH_LEN] = {};
    TopicSlot topics_[MaxTopics];
    FrameParser parser_;
    std::uint8_t rx_buf_[256];
    std::uint8_t frame_scratch_[MAX_FRAME];
    std::size_t bytes_in_ = 0;
    std::size_t bytes_out_ = 0;
    std::size_t frames_in_ = 0;
    std::size_t frames_out_ = 0;

    static std::size_t strnlen_(const char* s, std::size_t cap) noexcept {
        std::size_t n = 0;
        while (n < cap && s[n] != '\0') ++n;
        return n;
    }

    TopicSlot* find_(std::uint8_t topic_id) noexcept {
        for (auto& s : topics_) if (s.used && s.topic_id == topic_id) return &s;
        return nullptr;
    }

    TopicSlot* next_pending_() noexcept {
        for (auto& s : topics_) if (s.used && !s.acked) return &s;
        return nullptr;
    }

    bool send_(std::uint8_t msg_id, const std::uint8_t* payload, std::size_t len) noexcept {
        std::size_t n = 0;
        if (encode_frame(tx_seq_, msg_id, payload, len,
                         frame_scratch_, sizeof(frame_scratch_), &n) != EncodeStatus::Ok) {
            return false;
        }
        tx_seq_ = static_cast<std::uint8_t>(tx_seq_ + 1);
        if (!transport_.write(frame_scratch_, n)) return false;
        bytes_out_ += n;
        ++frames_out_;
        return true;
    }

    void send_hello_() noexcept {
        Hello h{};
        h.proto_ver = PROTOCOL_VERSION;
        std::memcpy(h.device_id, device_id_, DEVICE_ID_LEN);
        std::memcpy(h.fw_hash, fw_hash_, FW_HASH_LEN);
        h.max_payload = MAX_PAYLOAD;
        std::uint8_t body[64];
        std::size_t n = 0;
        encode_hello(h, body, sizeof(body), &n);
        send_(CONTROL_MSG_ID, body, n);
    }

    void send_advertise_(const TopicSlot& s) noexcept {
        std::uint8_t body[128];
        std::size_t n = 0;
        encode_advertise(s.topic_id, s.direction,
                         s.type_str, s.type_len,
                         s.name, s.name_len,
                         body, sizeof(body), &n);
        send_(CONTROL_MSG_ID, body, n);
    }

    void pump_rx_() noexcept {
        const auto got = transport_.read(rx_buf_, sizeof(rx_buf_));
        if (got == Transport::ErrorSentinel) {
            // Transport collapsed; restart the handshake.
            state_ = LeafState::SendHello;
            last_action_ms_ = 0;
            for (auto& s : topics_) s.acked = false;
            return;
        }
        if (got == 0) return;
        bytes_in_ += got;
        parser_.feed(rx_buf_, got, &LeafClient::on_frame_, this);
    }

    static void on_frame_(const DecodedView& v, void* user) noexcept {
        auto* self = static_cast<LeafClient*>(user);
        ++self->frames_in_;
        if (v.msg_id == CONTROL_MSG_ID) self->handle_control_(v);
        else self->handle_data_(v);
    }

    void handle_control_(const DecodedView& v) noexcept {
        Opcode op;
        if (peek_opcode(v.payload, v.payload_len, &op) != ControlStatus::Ok) return;
        switch (op) {
            case Opcode::HelloAck:
                if (state_ == LeafState::AwaitHelloAck) {
                    for (auto& s : topics_) s.acked = false;
                    state_ = LeafState::Advertise;
                }
                break;
            case Opcode::AdvertiseAck: {
                AdvertiseAck ack{};
                if (decode_advertise_ack(v.payload + 1, v.payload_len - 1, &ack) ==
                    ControlStatus::Ok) {
                    auto* s = find_(ack.topic_id);
                    if (s != nullptr && ack.accepted) s->acked = true;
                    if (state_ == LeafState::AwaitAdvertiseAck &&
                        ack.topic_id == pending_advertise_) {
                        state_ = LeafState::Advertise;
                    }
                }
                break;
            }
            case Opcode::Ping: {
                Ping p{};
                if (decode_ping(v.payload + 1, v.payload_len - 1, &p) ==
                    ControlStatus::Ok) {
                    std::uint8_t body[8];
                    std::size_t n = 0;
                    encode_pong({p.nonce}, body, sizeof(body), &n);
                    send_(CONTROL_MSG_ID, body, n);
                }
                break;
            }
            case Opcode::Bye:
                state_ = LeafState::SendHello;
                last_action_ms_ = 0;
                break;
            default:
                break;
        }
    }

    void handle_data_(const DecodedView& v) noexcept {
        auto* s = find_(v.msg_id);
        if (s == nullptr || s->direction != Direction::Subscribe) return;
        if (s->on_payload != nullptr) {
            s->on_payload(v.payload, v.payload_len, s->on_payload_user);
        }
    }
};

}  // namespace rosserial2
