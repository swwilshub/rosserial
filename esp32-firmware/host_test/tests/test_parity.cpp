// Cross-language parity tests.
//
// The Python codec produces:
//   - tests/golden/*.bin: hand-curated frames
//   - tests/corpus/wire_v1_records.bin: input vectors (seq, msg_id, payload)
//   - tests/corpus/wire_v1_frames.bin:  the corresponding encoded frames
//
// The C++ codec must:
//   1) decode every frame in wire_v1_frames.bin and reproduce the
//      record bytes
//   2) encode every record from wire_v1_records.bin and produce a
//      byte-identical match to wire_v1_frames.bin
//
// Together these prove the two codecs agree on the wire format.

#include <catch2/catch_test_macros.hpp>
#include <cstring>
#include <string>

#include "rosserial2/codec.hpp"
#include "rosserial2/control.hpp"
#include "test_helpers.hpp"

using namespace rosserial2;

namespace {

struct Record {
    std::uint8_t seq;
    std::uint8_t msg_id;
    std::vector<std::uint8_t> payload;
};

std::vector<Record> parse_records(const std::vector<std::uint8_t>& bytes) {
    std::vector<Record> out;
    std::size_t i = 0;
    while (i < bytes.size()) {
        REQUIRE(bytes.size() - i >= 4);
        Record r{};
        r.seq = bytes[i++];
        r.msg_id = bytes[i++];
        const std::size_t len = static_cast<std::size_t>(bytes[i]) |
                                (static_cast<std::size_t>(bytes[i + 1]) << 8);
        i += 2;
        REQUIRE(bytes.size() - i >= len);
        r.payload.assign(bytes.begin() + static_cast<long>(i),
                         bytes.begin() + static_cast<long>(i + len));
        i += len;
        out.push_back(std::move(r));
    }
    return out;
}

}  // namespace

TEST_CASE("corpus: C++ decoder produces records that match Python", "[parity]") {
    const auto records_bin = test_helpers::read_file(
        std::string(ROSSERIAL2_CORPUS_DIR) + "/wire_v1_records.bin");
    const auto frames_bin = test_helpers::read_file(
        std::string(ROSSERIAL2_CORPUS_DIR) + "/wire_v1_frames.bin");
    REQUIRE_FALSE(records_bin.empty());
    REQUIRE_FALSE(frames_bin.empty());
    const auto records = parse_records(records_bin);
    REQUIRE(records.size() == 256);

    FrameParser parser;
    test_helpers::Sink sink;
    parser.feed(frames_bin.data(), frames_bin.size(),
                test_helpers::capture_cb, &sink);
    REQUIRE(parser.errors() == 0);
    REQUIRE(sink.frames.size() == records.size());
    for (std::size_t i = 0; i < records.size(); ++i) {
        INFO("record " << i);
        REQUIRE(sink.frames[i].seq == records[i].seq);
        REQUIRE(sink.frames[i].msg_id == records[i].msg_id);
        REQUIRE(sink.frames[i].payload == records[i].payload);
    }
}

TEST_CASE("corpus: C++ encoder reproduces Python frame bytes exactly", "[parity]") {
    const auto records_bin = test_helpers::read_file(
        std::string(ROSSERIAL2_CORPUS_DIR) + "/wire_v1_records.bin");
    const auto frames_bin = test_helpers::read_file(
        std::string(ROSSERIAL2_CORPUS_DIR) + "/wire_v1_frames.bin");
    REQUIRE_FALSE(records_bin.empty());
    const auto records = parse_records(records_bin);

    std::vector<std::uint8_t> rebuilt;
    rebuilt.reserve(frames_bin.size());
    std::uint8_t buf[MAX_FRAME];
    for (const auto& r : records) {
        std::size_t n = 0;
        const auto s = encode_frame(
            r.seq, r.msg_id,
            r.payload.empty() ? nullptr : r.payload.data(),
            r.payload.size(),
            buf, sizeof(buf), &n);
        REQUIRE(s == EncodeStatus::Ok);
        rebuilt.insert(rebuilt.end(), buf, buf + n);
    }
    REQUIRE(rebuilt.size() == frames_bin.size());
    REQUIRE(std::memcmp(rebuilt.data(), frames_bin.data(), rebuilt.size()) == 0);
}

TEST_CASE("golden frames decode in C++", "[parity][golden]") {
    struct GoldenCase {
        const char* file;
        std::uint8_t seq;
        std::uint8_t msg_id;
        std::vector<std::uint8_t> payload;
    };

    auto big_payload = std::vector<std::uint8_t>(MAX_PAYLOAD, 0);
    for (std::size_t i = 0; i < MAX_PAYLOAD; ++i) {
        big_payload[i] = static_cast<std::uint8_t>(i % 256);
    }

    const std::string greeting = "hello, rosserial2";
    const std::vector<std::uint8_t> ascii(greeting.begin(), greeting.end());

    const std::vector<GoldenCase> cases{
        {"empty_payload.bin", 0, 1, {}},
        {"ascii_payload.bin", 42, 7, ascii},
        {"max_payload.bin", 255, 255, big_payload},
    };
    for (const auto& c : cases) {
        INFO("golden file " << c.file);
        const auto bytes = test_helpers::read_file(
            std::string(ROSSERIAL2_GOLDEN_DIR) + "/" + c.file);
        REQUIRE_FALSE(bytes.empty());
        DecodedView v{};
        REQUIRE(decode_frame(bytes.data(), bytes.size(), &v) == DecodeStatus::Ok);
        REQUIRE(v.seq == c.seq);
        REQUIRE(v.msg_id == c.msg_id);
        REQUIRE(v.payload_len == c.payload.size());
        REQUIRE(std::memcmp(v.payload, c.payload.data(), c.payload.size()) == 0);
    }
}

TEST_CASE("golden HELLO frame parses with C++ control codec", "[parity][golden][control]") {
    const auto bytes = test_helpers::read_file(
        std::string(ROSSERIAL2_GOLDEN_DIR) + "/hello.bin");
    REQUIRE_FALSE(bytes.empty());
    DecodedView v{};
    REQUIRE(decode_frame(bytes.data(), bytes.size(), &v) == DecodeStatus::Ok);
    REQUIRE(v.msg_id == CONTROL_MSG_ID);
    Opcode op{};
    REQUIRE(peek_opcode(v.payload, v.payload_len, &op) == ControlStatus::Ok);
    REQUIRE(op == Opcode::Hello);
    Hello h{};
    REQUIRE(decode_hello(v.payload + 1, v.payload_len - 1, &h) == ControlStatus::Ok);
    REQUIRE(h.proto_ver == 1);
    REQUIRE(h.max_payload == 512);
    for (auto b : h.device_id) REQUIRE(b == 0xAA);
    for (auto b : h.fw_hash) REQUIRE(b == 0xBB);
}

TEST_CASE("golden ADVERTISE parses with C++ control codec", "[parity][golden][control]") {
    const auto bytes = test_helpers::read_file(
        std::string(ROSSERIAL2_GOLDEN_DIR) + "/advertise.bin");
    REQUIRE_FALSE(bytes.empty());
    DecodedView v{};
    REQUIRE(decode_frame(bytes.data(), bytes.size(), &v) == DecodeStatus::Ok);
    Opcode op{};
    REQUIRE(peek_opcode(v.payload, v.payload_len, &op) == ControlStatus::Ok);
    REQUIRE(op == Opcode::Advertise);
    AdvertiseView av{};
    REQUIRE(decode_advertise(v.payload + 1, v.payload_len - 1, &av) == ControlStatus::Ok);
    REQUIRE(av.topic_id == 7);
    REQUIRE(av.direction == Direction::Publish);
    const std::string type(av.type_str, av.type_str + av.type_len);
    const std::string name(av.name, av.name + av.name_len);
    REQUIRE(type == "std_msgs/msg/String");
    REQUIRE(name == "chatter");
}

TEST_CASE("golden PING parses with C++ control codec", "[parity][golden][control]") {
    const auto bytes = test_helpers::read_file(
        std::string(ROSSERIAL2_GOLDEN_DIR) + "/ping.bin");
    REQUIRE_FALSE(bytes.empty());
    DecodedView v{};
    REQUIRE(decode_frame(bytes.data(), bytes.size(), &v) == DecodeStatus::Ok);
    Opcode op{};
    REQUIRE(peek_opcode(v.payload, v.payload_len, &op) == ControlStatus::Ok);
    REQUIRE(op == Opcode::Ping);
    Ping p{};
    REQUIRE(decode_ping(v.payload + 1, v.payload_len - 1, &p) == ControlStatus::Ok);
    REQUIRE(p.nonce == 0xDEADBEEFu);
}
