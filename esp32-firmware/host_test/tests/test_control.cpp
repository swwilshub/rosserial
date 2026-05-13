#include <catch2/catch_test_macros.hpp>
#include <cstring>
#include <random>

#include "rosserial2/control.hpp"

using namespace rosserial2;

TEST_CASE("HELLO roundtrip", "[control]") {
    Hello in{};
    in.proto_ver = 1;
    for (auto& b : in.device_id) b = 0xAB;
    for (auto& b : in.fw_hash) b = 0xCD;
    in.max_payload = 512;
    std::uint8_t buf[64];
    std::size_t n = 0;
    REQUIRE(encode_hello(in, buf, sizeof(buf), &n) == ControlStatus::Ok);
    REQUIRE(buf[0] == static_cast<std::uint8_t>(Opcode::Hello));
    Opcode op{};
    REQUIRE(peek_opcode(buf, n, &op) == ControlStatus::Ok);
    REQUIRE(op == Opcode::Hello);
    Hello out{};
    REQUIRE(decode_hello(buf + 1, n - 1, &out) == ControlStatus::Ok);
    REQUIRE(out.proto_ver == in.proto_ver);
    REQUIRE(out.max_payload == in.max_payload);
    REQUIRE(std::memcmp(out.device_id, in.device_id, DEVICE_ID_LEN) == 0);
    REQUIRE(std::memcmp(out.fw_hash, in.fw_hash, FW_HASH_LEN) == 0);
}

TEST_CASE("HELLO_ACK roundtrip", "[control]") {
    HelloAck in{1, 1, 0xDEADBEEFu};
    std::uint8_t buf[16];
    std::size_t n = 0;
    REQUIRE(encode_hello_ack(in, buf, sizeof(buf), &n) == ControlStatus::Ok);
    HelloAck out{};
    REQUIRE(decode_hello_ack(buf + 1, n - 1, &out) == ControlStatus::Ok);
    REQUIRE(out.proto_ver == 1);
    REQUIRE(out.accepted == 1);
    REQUIRE(out.session_id == 0xDEADBEEFu);
}

TEST_CASE("PING / PONG roundtrip", "[control]") {
    std::uint8_t buf[8];
    std::size_t n = 0;
    Ping in{0x12345678u};
    REQUIRE(encode_ping(in, buf, sizeof(buf), &n) == ControlStatus::Ok);
    REQUIRE(buf[0] == static_cast<std::uint8_t>(Opcode::Ping));
    Ping out{};
    REQUIRE(decode_ping(buf + 1, n - 1, &out) == ControlStatus::Ok);
    REQUIRE(out.nonce == in.nonce);
    REQUIRE(encode_pong(Pong{in.nonce}, buf, sizeof(buf), &n) == ControlStatus::Ok);
    REQUIRE(buf[0] == static_cast<std::uint8_t>(Opcode::Pong));
    Pong p{};
    REQUIRE(decode_pong(buf + 1, n - 1, &p) == ControlStatus::Ok);
    REQUIRE(p.nonce == in.nonce);
}

TEST_CASE("ADVERTISE roundtrip", "[control]") {
    const char* type = "std_msgs/msg/String";
    const char* name = "chatter";
    std::uint8_t buf[80];
    std::size_t n = 0;
    REQUIRE(encode_advertise(7, Direction::Publish,
                             type, static_cast<std::uint8_t>(std::strlen(type)),
                             name, static_cast<std::uint8_t>(std::strlen(name)),
                             buf, sizeof(buf), &n) == ControlStatus::Ok);
    REQUIRE(buf[0] == static_cast<std::uint8_t>(Opcode::Advertise));
    AdvertiseView v{};
    REQUIRE(decode_advertise(buf + 1, n - 1, &v) == ControlStatus::Ok);
    REQUIRE(v.topic_id == 7);
    REQUIRE(v.direction == Direction::Publish);
    REQUIRE(v.type_len == std::strlen(type));
    REQUIRE(v.name_len == std::strlen(name));
    REQUIRE(std::memcmp(v.type_str, type, v.type_len) == 0);
    REQUIRE(std::memcmp(v.name, name, v.name_len) == 0);
}

TEST_CASE("ADVERTISE_ACK roundtrip", "[control]") {
    AdvertiseAck in{7, 1};
    std::uint8_t buf[8];
    std::size_t n = 0;
    REQUIRE(encode_advertise_ack(in, buf, sizeof(buf), &n) == ControlStatus::Ok);
    AdvertiseAck out{};
    REQUIRE(decode_advertise_ack(buf + 1, n - 1, &out) == ControlStatus::Ok);
    REQUIRE(out.topic_id == 7);
    REQUIRE(out.accepted == 1);
}

TEST_CASE("BYE roundtrip", "[control]") {
    Bye in{3};
    std::uint8_t buf[4];
    std::size_t n = 0;
    REQUIRE(encode_bye(in, buf, sizeof(buf), &n) == ControlStatus::Ok);
    Bye out{};
    REQUIRE(decode_bye(buf + 1, n - 1, &out) == ControlStatus::Ok);
    REQUIRE(out.reason == 3);
}

TEST_CASE("peek_opcode rejects unknown", "[control]") {
    const std::uint8_t bad[] = {0x42};
    Opcode op{};
    REQUIRE(peek_opcode(bad, sizeof(bad), &op) == ControlStatus::UnknownOpcode);
    REQUIRE(peek_opcode(bad, 0, &op) == ControlStatus::EmptyPayload);
}

TEST_CASE("ADVERTISE rejects empty fields and topic_id 0", "[control]") {
    std::uint8_t buf[16];
    std::size_t n = 0;
    REQUIRE(encode_advertise(0, Direction::Publish, "x", 1, "y", 1,
                             buf, sizeof(buf), &n) == ControlStatus::BadField);
    REQUIRE(encode_advertise(1, Direction::Publish, "", 0, "y", 1,
                             buf, sizeof(buf), &n) == ControlStatus::BadField);
    REQUIRE(encode_advertise(1, Direction::Publish, "x", 1, "", 0,
                             buf, sizeof(buf), &n) == ControlStatus::BadField);
}

TEST_CASE("decode_advertise rejects bad direction", "[control]") {
    const std::uint8_t body[] = {1, 2, 1, 'a', 1, 'b'};  // dir=2 invalid
    AdvertiseView v{};
    REQUIRE(decode_advertise(body, sizeof(body), &v) == ControlStatus::BadField);
}

TEST_CASE("decode_advertise rejects truncated", "[control]") {
    const std::uint8_t body[] = {1, 0, 10, 'a', 'b'};  // claims 10-byte type
    AdvertiseView v{};
    REQUIRE(decode_advertise(body, sizeof(body), &v) == ControlStatus::BadLength);
}

TEST_CASE("decode_hello rejects bad length", "[control]") {
    const std::uint8_t body[] = {1, 2, 3};
    Hello h{};
    REQUIRE(decode_hello(body, sizeof(body), &h) == ControlStatus::BadLength);
}
