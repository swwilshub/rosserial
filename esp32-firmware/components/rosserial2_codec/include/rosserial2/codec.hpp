// rosserial2 wire codec — header-only, no allocations, C++17.
//
// Frame layout (little-endian):
//     0xAA 0x55  LEN_LO LEN_HI  SEQ  MSG_ID  PAYLOAD...  CRC32
// CRC32 = IEEE 802.3 over LEN_LO..end-of-payload.
//
// This header is shared between the ESP-IDF firmware build and the
// host-side unit tests. It depends on <cstddef>, <cstdint>, and
// <cstring> only.

#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace rosserial2 {

inline constexpr std::uint8_t SYNC0 = 0xAA;
inline constexpr std::uint8_t SYNC1 = 0x55;
inline constexpr std::size_t HEADER_SIZE = 6;  // SYNC(2)+LEN(2)+SEQ(1)+MSG_ID(1)
inline constexpr std::size_t CRC_SIZE = 4;
inline constexpr std::size_t OVERHEAD = HEADER_SIZE + CRC_SIZE;  // 10
inline constexpr std::size_t MAX_PAYLOAD = 512;
inline constexpr std::size_t MAX_FRAME = MAX_PAYLOAD + OVERHEAD;
inline constexpr std::uint8_t CONTROL_MSG_ID = 0;
inline constexpr std::uint8_t PROTOCOL_VERSION = 1;

enum class EncodeStatus : std::uint8_t {
    Ok = 0,
    PayloadTooLarge,
    OutputBufferTooSmall,
};

enum class DecodeStatus : std::uint8_t {
    Ok = 0,
    BufferTooShort,
    BadSync,
    LengthOutOfRange,
    SizeMismatch,
    CrcMismatch,
};

// IEEE 802.3 CRC32, poly 0xEDB88320, init 0xFFFFFFFF, xorout 0xFFFFFFFF.
// Computed bitwise — small and table-free, fine on ESP32 at our rates.
inline std::uint32_t crc32(const std::uint8_t* data, std::size_t n) noexcept {
    std::uint32_t crc = 0xFFFFFFFFu;
    for (std::size_t i = 0; i < n; ++i) {
        crc ^= data[i];
        for (int b = 0; b < 8; ++b) {
            std::uint32_t mask = -static_cast<std::int32_t>(crc & 1u);
            crc = (crc >> 1) ^ (0xEDB88320u & mask);
        }
    }
    return ~crc;
}

// Write a frame to ``out``. Returns Ok and sets ``out_size`` to the
// number of bytes written. ``out`` must have capacity ``out_cap`` bytes;
// the worst case is ``OVERHEAD + payload_len``.
inline EncodeStatus encode_frame(std::uint8_t seq,
                                 std::uint8_t msg_id,
                                 const std::uint8_t* payload,
                                 std::size_t payload_len,
                                 std::uint8_t* out,
                                 std::size_t out_cap,
                                 std::size_t* out_size) noexcept {
    if (payload_len > MAX_PAYLOAD) {
        return EncodeStatus::PayloadTooLarge;
    }
    const std::size_t total = OVERHEAD + payload_len;
    if (out_cap < total) {
        return EncodeStatus::OutputBufferTooSmall;
    }
    out[0] = SYNC0;
    out[1] = SYNC1;
    out[2] = static_cast<std::uint8_t>(payload_len & 0xFF);
    out[3] = static_cast<std::uint8_t>((payload_len >> 8) & 0xFF);
    out[4] = seq;
    out[5] = msg_id;
    if (payload_len > 0) {
        std::memcpy(out + HEADER_SIZE, payload, payload_len);
    }
    // CRC covers LEN_LO..end-of-payload.
    const std::uint32_t c = crc32(out + 2, HEADER_SIZE - 2 + payload_len);
    const std::size_t crc_off = HEADER_SIZE + payload_len;
    out[crc_off + 0] = static_cast<std::uint8_t>(c & 0xFF);
    out[crc_off + 1] = static_cast<std::uint8_t>((c >> 8) & 0xFF);
    out[crc_off + 2] = static_cast<std::uint8_t>((c >> 16) & 0xFF);
    out[crc_off + 3] = static_cast<std::uint8_t>((c >> 24) & 0xFF);
    if (out_size != nullptr) {
        *out_size = total;
    }
    return EncodeStatus::Ok;
}

// Decode a single complete frame from ``buf``. Caller must pass exactly
// one frame's worth of bytes; for streaming, use ``FrameParser``.
//
// On Ok the payload pointer (into ``buf``) and length are written.
struct DecodedView {
    std::uint8_t seq;
    std::uint8_t msg_id;
    const std::uint8_t* payload;
    std::size_t payload_len;
};

inline DecodeStatus decode_frame(const std::uint8_t* buf,
                                 std::size_t n,
                                 DecodedView* out) noexcept {
    if (n < OVERHEAD) {
        return DecodeStatus::BufferTooShort;
    }
    if (buf[0] != SYNC0 || buf[1] != SYNC1) {
        return DecodeStatus::BadSync;
    }
    const std::size_t length =
        static_cast<std::size_t>(buf[2]) | (static_cast<std::size_t>(buf[3]) << 8);
    if (length > MAX_PAYLOAD) {
        return DecodeStatus::LengthOutOfRange;
    }
    const std::size_t total = OVERHEAD + length;
    if (n != total) {
        return DecodeStatus::SizeMismatch;
    }
    const std::size_t crc_off = HEADER_SIZE + length;
    const std::uint32_t crc_actual =
        static_cast<std::uint32_t>(buf[crc_off]) |
        (static_cast<std::uint32_t>(buf[crc_off + 1]) << 8) |
        (static_cast<std::uint32_t>(buf[crc_off + 2]) << 16) |
        (static_cast<std::uint32_t>(buf[crc_off + 3]) << 24);
    const std::uint32_t crc_expected = crc32(buf + 2, HEADER_SIZE - 2 + length);
    if (crc_actual != crc_expected) {
        return DecodeStatus::CrcMismatch;
    }
    if (out != nullptr) {
        out->seq = buf[4];
        out->msg_id = buf[5];
        out->payload = buf + HEADER_SIZE;
        out->payload_len = length;
    }
    return DecodeStatus::Ok;
}

// Streaming parser. Fixed-size internal buffer; no allocations. The
// caller feeds bytes and gets a callback per decoded frame. Resync
// strategy mirrors the Python parser exactly: on any failure drop one
// byte past the leading 0xAA and keep scanning.
class FrameParser {
public:
    // ``Callback`` is invoked with (seq, msg_id, payload, payload_len)
    // for each complete frame. The payload pointer is valid only for
    // the duration of the callback.
    using Callback = void (*)(const DecodedView& view, void* user);

    FrameParser() = default;

    void reset() noexcept {
        buf_len_ = 0;
        errors_ = 0;
    }

    std::size_t errors() const noexcept { return errors_; }

    // Feed bytes; invoke ``cb`` for each complete frame produced.
    void feed(const std::uint8_t* data, std::size_t n,
              Callback cb, void* user) noexcept {
        for (std::size_t i = 0; i < n; ++i) {
            // If the buffer is at capacity (which only happens when the
            // longest possible frame is in-flight and still incomplete),
            // drop the oldest byte before appending. In practice the
            // resync logic below empties the buffer well before this
            // bound, so this only fires when a pathological producer
            // sends nothing but plausible sync sequences.
            if (buf_len_ == MAX_FRAME) {
                drop_one_();
                ++errors_;
            }
            buf_[buf_len_++] = data[i];
            // Drain as many frames (and as much garbage) as possible.
            while (try_one_(cb, user)) {
                // keep going
            }
        }
    }

private:
    std::uint8_t buf_[MAX_FRAME];
    std::size_t buf_len_ = 0;
    std::size_t errors_ = 0;

    void drop_one_() noexcept {
        if (buf_len_ <= 1) {
            buf_len_ = 0;
            return;
        }
        std::memmove(buf_, buf_ + 1, buf_len_ - 1);
        --buf_len_;
    }

    // Discard ``k`` leading bytes from the buffer.
    void advance_(std::size_t k) noexcept {
        if (k >= buf_len_) {
            buf_len_ = 0;
            return;
        }
        std::memmove(buf_, buf_ + k, buf_len_ - k);
        buf_len_ -= k;
    }

    // Try to extract one frame from the head of the buffer. Returns
    // true if it made forward progress (frame emitted, or junk
    // consumed). False means "need more data".
    bool try_one_(Callback cb, void* user) noexcept {
        if (buf_len_ == 0) {
            return false;
        }
        // Find the first 0xAA.
        std::size_t start = 0;
        while (start < buf_len_ && buf_[start] != SYNC0) {
            ++start;
        }
        if (start > 0) {
            advance_(start);
            return true;  // junk consumed
        }
        if (buf_len_ < 2) {
            return false;
        }
        if (buf_[1] != SYNC1) {
            advance_(1);
            return true;
        }
        if (buf_len_ < HEADER_SIZE) {
            return false;
        }
        const std::size_t length =
            static_cast<std::size_t>(buf_[2]) | (static_cast<std::size_t>(buf_[3]) << 8);
        if (length > MAX_PAYLOAD) {
            ++errors_;
            advance_(1);  // rewind past the 0xAA
            return true;
        }
        const std::size_t total = OVERHEAD + length;
        if (buf_len_ < total) {
            return false;
        }
        const std::size_t crc_off = HEADER_SIZE + length;
        const std::uint32_t crc_actual =
            static_cast<std::uint32_t>(buf_[crc_off]) |
            (static_cast<std::uint32_t>(buf_[crc_off + 1]) << 8) |
            (static_cast<std::uint32_t>(buf_[crc_off + 2]) << 16) |
            (static_cast<std::uint32_t>(buf_[crc_off + 3]) << 24);
        const std::uint32_t crc_expected = crc32(buf_ + 2, HEADER_SIZE - 2 + length);
        if (crc_actual != crc_expected) {
            ++errors_;
            advance_(1);
            return true;
        }
        DecodedView view{buf_[4], buf_[5], buf_ + HEADER_SIZE, length};
        if (cb != nullptr) {
            cb(view, user);
        }
        advance_(total);
        return true;
    }
};

}  // namespace rosserial2
