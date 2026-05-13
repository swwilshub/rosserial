// Control-plane opcode encoders/decoders, header-only, no allocations.
//
// Opcodes are an exact mirror of ros2-bridge/rosserial2/control.py.

#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

#include "rosserial2/codec.hpp"

namespace rosserial2 {

inline constexpr std::size_t DEVICE_ID_LEN = 16;
inline constexpr std::size_t FW_HASH_LEN = 20;

enum class Opcode : std::uint8_t {
    Hello = 0x01,
    HelloAck = 0x02,
    Advertise = 0x03,
    AdvertiseAck = 0x04,
    Ping = 0x05,
    Pong = 0x06,
    Log = 0x07,
    Bye = 0xFF,
};

enum class Direction : std::uint8_t {
    Publish = 0,
    Subscribe = 1,
};

enum class ControlStatus : std::uint8_t {
    Ok = 0,
    EmptyPayload,
    UnknownOpcode,
    BadLength,
    BadField,
    OutputBufferTooSmall,
};

// --- HELLO -----------------------------------------------------------

struct Hello {
    std::uint8_t proto_ver;
    std::uint8_t device_id[DEVICE_ID_LEN];
    std::uint8_t fw_hash[FW_HASH_LEN];
    std::uint16_t max_payload;
};

inline ControlStatus encode_hello(const Hello& h,
                                  std::uint8_t* out,
                                  std::size_t out_cap,
                                  std::size_t* out_size) noexcept {
    constexpr std::size_t total = 1 + 1 + DEVICE_ID_LEN + FW_HASH_LEN + 2;
    if (out_cap < total) return ControlStatus::OutputBufferTooSmall;
    out[0] = static_cast<std::uint8_t>(Opcode::Hello);
    out[1] = h.proto_ver;
    std::memcpy(out + 2, h.device_id, DEVICE_ID_LEN);
    std::memcpy(out + 2 + DEVICE_ID_LEN, h.fw_hash, FW_HASH_LEN);
    const std::size_t mp_off = 2 + DEVICE_ID_LEN + FW_HASH_LEN;
    out[mp_off + 0] = static_cast<std::uint8_t>(h.max_payload & 0xFF);
    out[mp_off + 1] = static_cast<std::uint8_t>((h.max_payload >> 8) & 0xFF);
    if (out_size) *out_size = total;
    return ControlStatus::Ok;
}

inline ControlStatus decode_hello(const std::uint8_t* body,
                                  std::size_t n,
                                  Hello* out) noexcept {
    constexpr std::size_t expected = 1 + DEVICE_ID_LEN + FW_HASH_LEN + 2;
    if (n != expected) return ControlStatus::BadLength;
    out->proto_ver = body[0];
    std::memcpy(out->device_id, body + 1, DEVICE_ID_LEN);
    std::memcpy(out->fw_hash, body + 1 + DEVICE_ID_LEN, FW_HASH_LEN);
    const std::size_t mp_off = 1 + DEVICE_ID_LEN + FW_HASH_LEN;
    out->max_payload = static_cast<std::uint16_t>(body[mp_off]) |
                       (static_cast<std::uint16_t>(body[mp_off + 1]) << 8);
    return ControlStatus::Ok;
}

// --- HELLO_ACK -------------------------------------------------------

struct HelloAck {
    std::uint8_t proto_ver;
    std::uint8_t accepted;
    std::uint32_t session_id;
};

inline ControlStatus encode_hello_ack(const HelloAck& h,
                                      std::uint8_t* out,
                                      std::size_t out_cap,
                                      std::size_t* out_size) noexcept {
    constexpr std::size_t total = 1 + 1 + 1 + 4;
    if (out_cap < total) return ControlStatus::OutputBufferTooSmall;
    out[0] = static_cast<std::uint8_t>(Opcode::HelloAck);
    out[1] = h.proto_ver;
    out[2] = h.accepted;
    out[3] = static_cast<std::uint8_t>(h.session_id & 0xFF);
    out[4] = static_cast<std::uint8_t>((h.session_id >> 8) & 0xFF);
    out[5] = static_cast<std::uint8_t>((h.session_id >> 16) & 0xFF);
    out[6] = static_cast<std::uint8_t>((h.session_id >> 24) & 0xFF);
    if (out_size) *out_size = total;
    return ControlStatus::Ok;
}

inline ControlStatus decode_hello_ack(const std::uint8_t* body,
                                      std::size_t n,
                                      HelloAck* out) noexcept {
    if (n != 6) return ControlStatus::BadLength;
    out->proto_ver = body[0];
    out->accepted = body[1];
    out->session_id =
        static_cast<std::uint32_t>(body[2]) |
        (static_cast<std::uint32_t>(body[3]) << 8) |
        (static_cast<std::uint32_t>(body[4]) << 16) |
        (static_cast<std::uint32_t>(body[5]) << 24);
    return ControlStatus::Ok;
}

// --- PING / PONG -----------------------------------------------------

struct Ping { std::uint32_t nonce; };
struct Pong { std::uint32_t nonce; };

inline ControlStatus encode_ping(const Ping& p, std::uint8_t* out,
                                 std::size_t out_cap,
                                 std::size_t* out_size) noexcept {
    if (out_cap < 5) return ControlStatus::OutputBufferTooSmall;
    out[0] = static_cast<std::uint8_t>(Opcode::Ping);
    out[1] = static_cast<std::uint8_t>(p.nonce & 0xFF);
    out[2] = static_cast<std::uint8_t>((p.nonce >> 8) & 0xFF);
    out[3] = static_cast<std::uint8_t>((p.nonce >> 16) & 0xFF);
    out[4] = static_cast<std::uint8_t>((p.nonce >> 24) & 0xFF);
    if (out_size) *out_size = 5;
    return ControlStatus::Ok;
}

inline ControlStatus encode_pong(const Pong& p, std::uint8_t* out,
                                 std::size_t out_cap,
                                 std::size_t* out_size) noexcept {
    Ping pp{p.nonce};
    const auto s = encode_ping(pp, out, out_cap, out_size);
    if (s == ControlStatus::Ok) out[0] = static_cast<std::uint8_t>(Opcode::Pong);
    return s;
}

inline ControlStatus decode_ping(const std::uint8_t* body, std::size_t n,
                                 Ping* out) noexcept {
    if (n != 4) return ControlStatus::BadLength;
    out->nonce = static_cast<std::uint32_t>(body[0]) |
                 (static_cast<std::uint32_t>(body[1]) << 8) |
                 (static_cast<std::uint32_t>(body[2]) << 16) |
                 (static_cast<std::uint32_t>(body[3]) << 24);
    return ControlStatus::Ok;
}

inline ControlStatus decode_pong(const std::uint8_t* body, std::size_t n,
                                 Pong* out) noexcept {
    Ping p{};
    const auto s = decode_ping(body, n, &p);
    if (s == ControlStatus::Ok) out->nonce = p.nonce;
    return s;
}

// --- BYE -------------------------------------------------------------

struct Bye { std::uint8_t reason; };

inline ControlStatus encode_bye(const Bye& b, std::uint8_t* out,
                                std::size_t out_cap,
                                std::size_t* out_size) noexcept {
    if (out_cap < 2) return ControlStatus::OutputBufferTooSmall;
    out[0] = static_cast<std::uint8_t>(Opcode::Bye);
    out[1] = b.reason;
    if (out_size) *out_size = 2;
    return ControlStatus::Ok;
}

inline ControlStatus decode_bye(const std::uint8_t* body, std::size_t n,
                                Bye* out) noexcept {
    if (n != 1) return ControlStatus::BadLength;
    out->reason = body[0];
    return ControlStatus::Ok;
}

// --- ADVERTISE -------------------------------------------------------
//
// The C++ side does not allocate, so we expose a view-style decoder
// (pointers into the caller's buffer) rather than an owning struct.

struct AdvertiseView {
    std::uint8_t topic_id;
    Direction direction;
    const char* type_str;
    std::uint8_t type_len;
    const char* name;
    std::uint8_t name_len;
};

inline ControlStatus encode_advertise(std::uint8_t topic_id,
                                      Direction direction,
                                      const char* type_str,
                                      std::uint8_t type_len,
                                      const char* name,
                                      std::uint8_t name_len,
                                      std::uint8_t* out,
                                      std::size_t out_cap,
                                      std::size_t* out_size) noexcept {
    if (topic_id == 0) return ControlStatus::BadField;
    if (type_len == 0 || name_len == 0) return ControlStatus::BadField;
    const std::size_t total = 4 + type_len + 1 + name_len;
    if (out_cap < total) return ControlStatus::OutputBufferTooSmall;
    out[0] = static_cast<std::uint8_t>(Opcode::Advertise);
    out[1] = topic_id;
    out[2] = static_cast<std::uint8_t>(direction);
    out[3] = type_len;
    std::memcpy(out + 4, type_str, type_len);
    out[4 + type_len] = name_len;
    std::memcpy(out + 5 + type_len, name, name_len);
    if (out_size) *out_size = total;
    return ControlStatus::Ok;
}

inline ControlStatus decode_advertise(const std::uint8_t* body,
                                      std::size_t n,
                                      AdvertiseView* out) noexcept {
    if (n < 3) return ControlStatus::BadLength;
    const std::uint8_t topic_id = body[0];
    const std::uint8_t dir = body[1];
    const std::uint8_t type_len = body[2];
    if (dir > 1) return ControlStatus::BadField;
    if (n < std::size_t{3} + type_len + 1) return ControlStatus::BadLength;
    const std::uint8_t name_len = body[3 + type_len];
    if (n != std::size_t{4} + type_len + name_len) return ControlStatus::BadLength;
    out->topic_id = topic_id;
    out->direction = static_cast<Direction>(dir);
    out->type_str = reinterpret_cast<const char*>(body + 3);
    out->type_len = type_len;
    out->name = reinterpret_cast<const char*>(body + 4 + type_len);
    out->name_len = name_len;
    return ControlStatus::Ok;
}

// --- ADVERTISE_ACK ---------------------------------------------------

struct AdvertiseAck {
    std::uint8_t topic_id;
    std::uint8_t accepted;
};

inline ControlStatus encode_advertise_ack(const AdvertiseAck& a,
                                          std::uint8_t* out,
                                          std::size_t out_cap,
                                          std::size_t* out_size) noexcept {
    if (out_cap < 3) return ControlStatus::OutputBufferTooSmall;
    out[0] = static_cast<std::uint8_t>(Opcode::AdvertiseAck);
    out[1] = a.topic_id;
    out[2] = a.accepted;
    if (out_size) *out_size = 3;
    return ControlStatus::Ok;
}

inline ControlStatus decode_advertise_ack(const std::uint8_t* body,
                                          std::size_t n,
                                          AdvertiseAck* out) noexcept {
    if (n != 2) return ControlStatus::BadLength;
    out->topic_id = body[0];
    out->accepted = body[1];
    return ControlStatus::Ok;
}

// --- Top-level opcode peek ------------------------------------------

inline ControlStatus peek_opcode(const std::uint8_t* payload, std::size_t n,
                                 Opcode* out) noexcept {
    if (n == 0) return ControlStatus::EmptyPayload;
    switch (payload[0]) {
        case static_cast<std::uint8_t>(Opcode::Hello):
        case static_cast<std::uint8_t>(Opcode::HelloAck):
        case static_cast<std::uint8_t>(Opcode::Advertise):
        case static_cast<std::uint8_t>(Opcode::AdvertiseAck):
        case static_cast<std::uint8_t>(Opcode::Ping):
        case static_cast<std::uint8_t>(Opcode::Pong):
        case static_cast<std::uint8_t>(Opcode::Log):
        case static_cast<std::uint8_t>(Opcode::Bye):
            *out = static_cast<Opcode>(payload[0]);
            return ControlStatus::Ok;
        default:
            return ControlStatus::UnknownOpcode;
    }
}

}  // namespace rosserial2
