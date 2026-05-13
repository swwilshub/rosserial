#include <catch2/catch_test_macros.hpp>
#include <random>

#include "rosserial2/codec.hpp"
#include "test_helpers.hpp"

using namespace rosserial2;
using test_helpers::Sink;

TEST_CASE("parser locks onto frame after arbitrary junk prefix", "[resync]") {
    Sink sink;
    FrameParser parser;
    const std::vector<std::uint8_t> junk{
        0x00, 0xFF, 0xAA, 0xAB, 0x55, 0x55, 0xAA, 0x55,  // teaser sync — bad LEN coming
        0xFF, 0xFF,  // LEN > MAX_PAYLOAD → reject, rewind
        0x12, 0x34, 0x56,
    };
    const auto frame = test_helpers::encode(99, 1, {'o', 'k'});
    std::vector<std::uint8_t> stream = junk;
    stream.insert(stream.end(), frame.begin(), frame.end());
    parser.feed(stream.data(), stream.size(), test_helpers::capture_cb, &sink);
    REQUIRE(sink.frames.size() == 1);
    REQUIRE(sink.frames[0].seq == 99);
    REQUIRE(sink.frames[0].payload == std::vector<std::uint8_t>{'o', 'k'});
}

TEST_CASE("payload containing AA 55 does not confuse the parser", "[resync]") {
    Sink sink;
    FrameParser parser;
    std::vector<std::uint8_t> nasty(200);
    for (std::size_t i = 0; i + 1 < nasty.size(); i += 2) {
        nasty[i] = 0xAA;
        nasty[i + 1] = 0x55;
    }
    const auto f1 = test_helpers::encode(1, 1, nasty);
    const auto f2 = test_helpers::encode(2, 2, {'n', 'e', 'x', 't'});
    std::vector<std::uint8_t> stream = f1;
    stream.insert(stream.end(), f2.begin(), f2.end());
    parser.feed(stream.data(), stream.size(), test_helpers::capture_cb, &sink);
    REQUIRE(sink.frames.size() == 2);
    REQUIRE(sink.frames[0].payload == nasty);
    REQUIRE(sink.frames[1].payload == std::vector<std::uint8_t>{'n', 'e', 'x', 't'});
}

TEST_CASE("payload that looks like an inner frame is preserved", "[resync]") {
    Sink sink;
    FrameParser parser;
    const auto inner = test_helpers::encode(99, 99, {'t', 'r', 'i', 'c', 'k'});
    const auto outer = test_helpers::encode(1, 1, inner);
    const auto follow = test_helpers::encode(2, 2, {'a', 'f', 't', 'e', 'r'});
    std::vector<std::uint8_t> stream = outer;
    stream.insert(stream.end(), follow.begin(), follow.end());
    parser.feed(stream.data(), stream.size(), test_helpers::capture_cb, &sink);
    REQUIRE(sink.frames.size() == 2);
    REQUIRE(sink.frames[0].payload == inner);
    REQUIRE(sink.frames[1].payload == std::vector<std::uint8_t>{'a', 'f', 't', 'e', 'r'});
}

TEST_CASE("truncated frame does not poison the next one", "[resync]") {
    Sink sink;
    FrameParser parser;
    const auto enc = test_helpers::encode(5, 5, std::vector<std::uint8_t>(20, 0x42));
    const auto follow = test_helpers::encode(0, 0, {'a', 'f', 't', 'e', 'r'});
    const std::vector<std::uint8_t> pad(MAX_PAYLOAD + OVERHEAD, 0);
    for (std::size_t cut = 0; cut < enc.size(); ++cut) {
        sink.frames.clear();
        parser.reset();
        std::vector<std::uint8_t> stream(enc.begin(), enc.begin() + static_cast<long>(cut));
        stream.insert(stream.end(), follow.begin(), follow.end());
        stream.insert(stream.end(), pad.begin(), pad.end());
        parser.feed(stream.data(), stream.size(), test_helpers::capture_cb, &sink);
        bool found = false;
        for (const auto& f : sink.frames) {
            if (f.seq == 0 && f.msg_id == 0 &&
                f.payload == std::vector<std::uint8_t>{'a', 'f', 't', 'e', 'r'}) {
                found = true;
                break;
            }
        }
        REQUIRE(found);
    }
}

TEST_CASE("explicit resync bound: MAX_PAYLOAD + OVERHEAD bytes of junk", "[resync]") {
    Sink sink;
    FrameParser parser;
    std::vector<std::uint8_t> junk(MAX_PAYLOAD + OVERHEAD, 0xAA);  // worst case
    const auto good = test_helpers::encode(42, 7, {'h', 'e', 'l', 'l', 'o'});
    std::vector<std::uint8_t> stream = junk;
    stream.insert(stream.end(), good.begin(), good.end());
    parser.feed(stream.data(), stream.size(), test_helpers::capture_cb, &sink);
    REQUIRE(sink.frames.size() == 1);
    REQUIRE(sink.frames[0].seq == 42);
    REQUIRE(sink.frames[0].msg_id == 7);
    REQUIRE(sink.frames[0].payload == std::vector<std::uint8_t>{'h', 'e', 'l', 'l', 'o'});
}

TEST_CASE("bit-flip in frame N — frame N+1 still decodes", "[resync][bitflip]") {
    std::mt19937 rng(0xCAFEFEEDu);
    std::uniform_int_distribution<int> len_d(0, 32);
    std::uniform_int_distribution<int> byte_d(0, 255);
    const std::vector<std::uint8_t> pad(MAX_PAYLOAD + OVERHEAD, 0);
    for (int i = 0; i < 200; ++i) {
        std::vector<std::uint8_t> p(static_cast<std::size_t>(len_d(rng)));
        for (auto& b : p) b = static_cast<std::uint8_t>(byte_d(rng));
        auto bad = test_helpers::encode(0, 0, p);
        std::uniform_int_distribution<std::size_t> bit_d(0, bad.size() * 8 - 1);
        const auto bit = bit_d(rng);
        bad[bit / 8] ^= static_cast<std::uint8_t>(1u << (bit % 8));
        const auto good = test_helpers::encode(1, 0, {'r', 'e', 'c', 'o', 'v'});
        std::vector<std::uint8_t> stream = bad;
        stream.insert(stream.end(), good.begin(), good.end());
        stream.insert(stream.end(), pad.begin(), pad.end());
        Sink sink;
        FrameParser parser;
        parser.feed(stream.data(), stream.size(), test_helpers::capture_cb, &sink);
        bool found = false;
        for (const auto& f : sink.frames) {
            if (f.seq == 1 && f.msg_id == 0 &&
                f.payload == std::vector<std::uint8_t>{'r', 'e', 'c', 'o', 'v'}) {
                found = true;
                break;
            }
        }
        REQUIRE(found);
    }
}
