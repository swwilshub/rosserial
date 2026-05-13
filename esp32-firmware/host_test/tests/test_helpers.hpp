#pragma once

#include <cstddef>
#include <cstdint>
#include <fstream>
#include <random>
#include <string>
#include <vector>

#include "rosserial2/codec.hpp"

namespace test_helpers {

struct CapturedFrame {
    std::uint8_t seq;
    std::uint8_t msg_id;
    std::vector<std::uint8_t> payload;
};

struct Sink {
    std::vector<CapturedFrame> frames;
};

inline void capture_cb(const rosserial2::DecodedView& v, void* user) {
    auto* sink = static_cast<Sink*>(user);
    sink->frames.push_back(CapturedFrame{
        v.seq,
        v.msg_id,
        std::vector<std::uint8_t>(v.payload, v.payload + v.payload_len),
    });
}

inline std::vector<std::uint8_t> read_file(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return {};
    f.seekg(0, std::ios::end);
    const auto n = f.tellg();
    f.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> out(static_cast<std::size_t>(n));
    if (n > 0) f.read(reinterpret_cast<char*>(out.data()), n);
    return out;
}

inline std::vector<std::uint8_t> encode(std::uint8_t seq,
                                       std::uint8_t msg_id,
                                       const std::vector<std::uint8_t>& payload) {
    std::vector<std::uint8_t> out(rosserial2::OVERHEAD + payload.size());
    std::size_t n = 0;
    const auto s = rosserial2::encode_frame(
        seq, msg_id,
        payload.empty() ? nullptr : payload.data(),
        payload.size(),
        out.data(), out.size(), &n);
    if (s != rosserial2::EncodeStatus::Ok) return {};
    out.resize(n);
    return out;
}

}  // namespace test_helpers
