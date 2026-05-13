#include <catch2/catch_test_macros.hpp>
#include <random>

#include "rosserial2/codec.hpp"
#include "test_helpers.hpp"

using namespace rosserial2;
using test_helpers::CapturedFrame;
using test_helpers::Sink;

TEST_CASE("constants match the spec", "[codec]") {
    REQUIRE(SYNC0 == 0xAA);
    REQUIRE(SYNC1 == 0x55);
    REQUIRE(HEADER_SIZE == 6);
    REQUIRE(CRC_SIZE == 4);
    REQUIRE(OVERHEAD == 10);
    REQUIRE(MAX_PAYLOAD == 512);
}

TEST_CASE("encode rejects oversize payload", "[codec]") {
    std::uint8_t out[MAX_FRAME];
    std::size_t n = 0;
    std::uint8_t payload[MAX_PAYLOAD + 1]{};
    REQUIRE(encode_frame(0, 1, payload, sizeof(payload), out, sizeof(out), &n)
            == EncodeStatus::PayloadTooLarge);
}

TEST_CASE("encode rejects undersized output buffer", "[codec]") {
    std::uint8_t out[5];
    std::size_t n = 0;
    REQUIRE(encode_frame(0, 1, nullptr, 0, out, sizeof(out), &n)
            == EncodeStatus::OutputBufferTooSmall);
}

TEST_CASE("encode/decode roundtrip — fixed cases", "[codec]") {
    struct Case { std::uint8_t seq; std::uint8_t msg_id; std::vector<std::uint8_t> p; };
    std::vector<Case> cases{
        {0, 1, {}},
        {42, 7, {'h', 'i'}},
        {255, 255, std::vector<std::uint8_t>(MAX_PAYLOAD, 0xAB)},
        {1, 0, std::vector<std::uint8_t>{0xAA, 0x55, 0xAA, 0x55}},
    };
    for (const auto& c : cases) {
        const auto buf = test_helpers::encode(c.seq, c.msg_id, c.p);
        REQUIRE(buf.size() == OVERHEAD + c.p.size());
        DecodedView v{};
        REQUIRE(decode_frame(buf.data(), buf.size(), &v) == DecodeStatus::Ok);
        REQUIRE(v.seq == c.seq);
        REQUIRE(v.msg_id == c.msg_id);
        REQUIRE(v.payload_len == c.p.size());
        REQUIRE(std::vector<std::uint8_t>(v.payload, v.payload + v.payload_len) == c.p);
    }
}

TEST_CASE("randomized roundtrip — 10k cases (deterministic seed)", "[codec][roundtrip]") {
    std::mt19937 rng(0xC0DECAFEu);
    std::uniform_int_distribution<int> seq_d(0, 255);
    std::uniform_int_distribution<int> mid_d(0, 255);
    std::uniform_int_distribution<int> len_d(0, static_cast<int>(MAX_PAYLOAD));
    std::uniform_int_distribution<int> byte_d(0, 255);
    for (int i = 0; i < 10000; ++i) {
        const auto seq = static_cast<std::uint8_t>(seq_d(rng));
        const auto mid = static_cast<std::uint8_t>(mid_d(rng));
        std::vector<std::uint8_t> p(static_cast<std::size_t>(len_d(rng)));
        for (auto& b : p) b = static_cast<std::uint8_t>(byte_d(rng));
        const auto buf = test_helpers::encode(seq, mid, p);
        DecodedView v{};
        REQUIRE(decode_frame(buf.data(), buf.size(), &v) == DecodeStatus::Ok);
        REQUIRE(v.seq == seq);
        REQUIRE(v.msg_id == mid);
        REQUIRE(v.payload_len == p.size());
        REQUIRE(std::memcmp(v.payload, p.data(), p.size()) == 0);
    }
}

TEST_CASE("decode rejects bad sync", "[codec]") {
    auto buf = test_helpers::encode(0, 1, {'x'});
    buf[0] = 0x00;
    DecodedView v{};
    REQUIRE(decode_frame(buf.data(), buf.size(), &v) == DecodeStatus::BadSync);
}

TEST_CASE("decode rejects bad CRC", "[codec]") {
    auto buf = test_helpers::encode(7, 9, {'a', 'b', 'c'});
    buf.back() ^= 0x01;
    DecodedView v{};
    REQUIRE(decode_frame(buf.data(), buf.size(), &v) == DecodeStatus::CrcMismatch);
}

TEST_CASE("decode rejects buffer too short", "[codec]") {
    std::uint8_t buf[3]{};
    DecodedView v{};
    REQUIRE(decode_frame(buf, sizeof(buf), &v) == DecodeStatus::BufferTooShort);
}

TEST_CASE("decode rejects oversize length", "[codec]") {
    std::vector<std::uint8_t> buf(OVERHEAD + MAX_PAYLOAD + 1, 0);
    buf[0] = SYNC0;
    buf[1] = SYNC1;
    buf[2] = static_cast<std::uint8_t>((MAX_PAYLOAD + 1) & 0xFF);
    buf[3] = static_cast<std::uint8_t>(((MAX_PAYLOAD + 1) >> 8) & 0xFF);
    DecodedView v{};
    REQUIRE(decode_frame(buf.data(), buf.size(), &v) == DecodeStatus::LengthOutOfRange);
}

TEST_CASE("streaming parser — single frame", "[parser]") {
    Sink sink;
    FrameParser parser;
    const auto buf = test_helpers::encode(13, 7, {'p', 'q'});
    parser.feed(buf.data(), buf.size(), test_helpers::capture_cb, &sink);
    REQUIRE(sink.frames.size() == 1);
    REQUIRE(sink.frames[0].seq == 13);
    REQUIRE(sink.frames[0].msg_id == 7);
    REQUIRE(sink.frames[0].payload == std::vector<std::uint8_t>{'p', 'q'});
    REQUIRE(parser.errors() == 0);
}

TEST_CASE("streaming parser — arbitrary chunking", "[parser]") {
    Sink sink;
    FrameParser parser;
    std::vector<std::uint8_t> stream;
    std::vector<CapturedFrame> expected;
    std::mt19937 rng(123);
    std::uniform_int_distribution<int> len_d(0, 60);
    std::uniform_int_distribution<int> byte_d(0, 255);
    for (int i = 0; i < 50; ++i) {
        std::vector<std::uint8_t> p(static_cast<std::size_t>(len_d(rng)));
        for (auto& b : p) b = static_cast<std::uint8_t>(byte_d(rng));
        const auto buf = test_helpers::encode(static_cast<std::uint8_t>(i & 0xFF),
                                              static_cast<std::uint8_t>((i + 1) & 0xFF), p);
        stream.insert(stream.end(), buf.begin(), buf.end());
        expected.push_back({static_cast<std::uint8_t>(i & 0xFF),
                            static_cast<std::uint8_t>((i + 1) & 0xFF), p});
    }
    // Feed in chunks of 7 bytes to stress state-machine boundaries.
    constexpr std::size_t chunk = 7;
    for (std::size_t i = 0; i < stream.size(); i += chunk) {
        const std::size_t take = std::min(chunk, stream.size() - i);
        parser.feed(stream.data() + i, take, test_helpers::capture_cb, &sink);
    }
    REQUIRE(sink.frames.size() == expected.size());
    for (std::size_t i = 0; i < expected.size(); ++i) {
        REQUIRE(sink.frames[i].seq == expected[i].seq);
        REQUIRE(sink.frames[i].msg_id == expected[i].msg_id);
        REQUIRE(sink.frames[i].payload == expected[i].payload);
    }
    REQUIRE(parser.errors() == 0);
}

TEST_CASE("bit-flip detected for randomized frames", "[codec][bitflip]") {
    std::mt19937 rng(0xBADBEEFu);
    std::uniform_int_distribution<int> seq_d(0, 255);
    std::uniform_int_distribution<int> mid_d(0, 255);
    std::uniform_int_distribution<int> len_d(0, 64);
    for (int i = 0; i < 1000; ++i) {
        const auto seq = static_cast<std::uint8_t>(seq_d(rng));
        const auto mid = static_cast<std::uint8_t>(mid_d(rng));
        std::vector<std::uint8_t> p(static_cast<std::size_t>(len_d(rng)));
        for (auto& b : p) b = static_cast<std::uint8_t>(seq ^ mid ^ i);
        auto buf = test_helpers::encode(seq, mid, p);
        std::uniform_int_distribution<std::size_t> bit_d(0, buf.size() * 8 - 1);
        const auto bit = bit_d(rng);
        buf[bit / 8] ^= static_cast<std::uint8_t>(1u << (bit % 8));
        DecodedView v{};
        const auto s = decode_frame(buf.data(), buf.size(), &v);
        if (s == DecodeStatus::Ok) {
            // Different bytes ⇒ different observable frame.
            const bool different =
                v.seq != seq || v.msg_id != mid || v.payload_len != p.size() ||
                std::memcmp(v.payload, p.data(), p.size()) != 0;
            REQUIRE(different);
        }
    }
}
