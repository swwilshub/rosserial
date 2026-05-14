// LeafClient state-machine tests with a FakeTransport.
//
// Drives the C++ leaf through a full handshake by feeding it the
// bytes a real bridge would produce (encoded via the same codec).
// Asserts the leaf reaches Ready, publishes correctly, and recovers
// from a transport-level reset.

#include <catch2/catch_test_macros.hpp>
#include <cstring>
#include <deque>
#include <vector>

#include "rosserial2/codec.hpp"
#include "rosserial2/control.hpp"
#include "rosserial2/leaf_client.hpp"
#include "rosserial2/transport.hpp"

using namespace rosserial2;

namespace {

class FakeTransport final : public Transport {
public:
    std::deque<std::uint8_t> rx;     // bytes the host will deliver to the leaf
    std::vector<std::uint8_t> tx;    // bytes the leaf wrote out
    bool fail_read = false;

    std::size_t read(std::uint8_t* buf, std::size_t cap) noexcept override {
        if (fail_read) return ErrorSentinel;
        std::size_t got = 0;
        while (got < cap && !rx.empty()) {
            buf[got++] = rx.front();
            rx.pop_front();
        }
        return got;
    }
    bool write(const std::uint8_t* data, std::size_t len) noexcept override {
        tx.insert(tx.end(), data, data + len);
        return true;
    }
    const char* name() const noexcept override { return "fake"; }

    void deliver(const std::uint8_t* data, std::size_t len) {
        rx.insert(rx.end(), data, data + len);
    }
};

std::vector<std::uint8_t> encode_one(std::uint8_t seq, std::uint8_t msg_id,
                                     const std::uint8_t* payload, std::size_t len) {
    std::vector<std::uint8_t> out(OVERHEAD + len);
    std::size_t n = 0;
    REQUIRE(encode_frame(seq, msg_id, payload, len,
                         out.data(), out.size(), &n) == EncodeStatus::Ok);
    out.resize(n);
    return out;
}

// Decode every full frame in tx, returning them in order.
struct Captured { std::uint8_t seq; std::uint8_t msg_id; std::vector<std::uint8_t> payload; };
std::vector<Captured> decode_all(const std::vector<std::uint8_t>& bytes) {
    std::vector<Captured> out;
    FrameParser p;
    p.feed(bytes.data(), bytes.size(),
           [](const DecodedView& v, void* user) {
               auto* o = static_cast<std::vector<Captured>*>(user);
               o->push_back(Captured{v.seq, v.msg_id,
                                     std::vector<std::uint8_t>(v.payload, v.payload + v.payload_len)});
           },
           &out);
    return out;
}

void send_hello_ack(FakeTransport& t, std::uint8_t seq = 0) {
    HelloAck a{1, 1, 0xCAFEBABE};
    std::uint8_t body[16];
    std::size_t n = 0;
    REQUIRE(encode_hello_ack(a, body, sizeof(body), &n) == ControlStatus::Ok);
    auto enc = encode_one(seq, CONTROL_MSG_ID, body, n);
    t.deliver(enc.data(), enc.size());
}

void send_adv_ack(FakeTransport& t, std::uint8_t topic_id, std::uint8_t seq) {
    AdvertiseAck a{topic_id, 1};
    std::uint8_t body[4];
    std::size_t n = 0;
    REQUIRE(encode_advertise_ack(a, body, sizeof(body), &n) == ControlStatus::Ok);
    auto enc = encode_one(seq, CONTROL_MSG_ID, body, n);
    t.deliver(enc.data(), enc.size());
}

}  // namespace

TEST_CASE("LeafClient: handshake → Ready", "[leaf]") {
    FakeTransport t;
    LeafClient<4> client{t, /*hello_retry_ms=*/10};
    const std::uint8_t did[DEVICE_ID_LEN] = {1};
    const std::uint8_t fh[FW_HASH_LEN] = {2};
    client.set_identity(did, fh);

    std::uint8_t topic = client.advertise("counter", "std_msgs/msg/Int32",
                                          Direction::Publish);
    REQUIRE(topic != 0);

    // First poll fires HELLO immediately (last_action_ms is 0).
    client.poll(0);
    REQUIRE(client.state() == LeafState::AwaitHelloAck);
    auto frames = decode_all(t.tx);
    REQUIRE(frames.size() == 1);
    REQUIRE(frames[0].msg_id == CONTROL_MSG_ID);
    REQUIRE(frames[0].payload[0] == static_cast<std::uint8_t>(Opcode::Hello));

    // Bridge replies HELLO_ACK.
    send_hello_ack(t, /*seq=*/0);
    client.poll(1);
    // Should have moved to Advertise and immediately emitted ADVERTISE.
    REQUIRE(client.state() == LeafState::AwaitAdvertiseAck);
    auto all = decode_all(t.tx);
    REQUIRE(all.size() == 2);
    REQUIRE(all[1].payload[0] == static_cast<std::uint8_t>(Opcode::Advertise));

    // Bridge replies ADVERTISE_ACK.
    send_adv_ack(t, topic, /*seq=*/1);
    client.poll(2);
    REQUIRE(client.state() == LeafState::Ready);
    REQUIRE(client.ready());
}

TEST_CASE("LeafClient: publishes encoded payload after Ready", "[leaf]") {
    FakeTransport t;
    LeafClient<4> client{t, 10};
    const std::uint8_t did[DEVICE_ID_LEN] = {1};
    const std::uint8_t fh[FW_HASH_LEN] = {2};
    client.set_identity(did, fh);
    std::uint8_t topic = client.advertise("counter", "std_msgs/msg/Int32",
                                          Direction::Publish);

    client.poll(0);
    send_hello_ack(t, 0);
    client.poll(1);
    send_adv_ack(t, topic, 1);
    client.poll(2);
    REQUIRE(client.ready());
    t.tx.clear();  // discard handshake frames

    const std::uint8_t payload[4] = {0x78, 0x56, 0x34, 0x12};
    REQUIRE(client.publish(topic, payload, sizeof(payload)));
    auto out = decode_all(t.tx);
    REQUIRE(out.size() == 1);
    REQUIRE(out[0].msg_id == topic);
    REQUIRE(out[0].payload == std::vector<std::uint8_t>(payload, payload + 4));
}

TEST_CASE("LeafClient: replies to PING with PONG nonce", "[leaf]") {
    FakeTransport t;
    LeafClient<2> client{t, 10};
    const std::uint8_t did[DEVICE_ID_LEN] = {1};
    const std::uint8_t fh[FW_HASH_LEN] = {2};
    client.set_identity(did, fh);
    client.advertise("c", "std_msgs/msg/Int32", Direction::Publish);
    client.poll(0);
    send_hello_ack(t, 0);
    client.poll(1);
    send_adv_ack(t, 1, 1);
    client.poll(2);
    t.tx.clear();

    Ping p{0xDEADBEEFu};
    std::uint8_t body[8];
    std::size_t n = 0;
    encode_ping(p, body, sizeof(body), &n);
    auto frame = encode_one(2, CONTROL_MSG_ID, body, n);
    t.deliver(frame.data(), frame.size());
    client.poll(3);
    auto out = decode_all(t.tx);
    REQUIRE(out.size() == 1);
    REQUIRE(out[0].payload[0] == static_cast<std::uint8_t>(Opcode::Pong));
    Pong got{};
    REQUIRE(decode_pong(out[0].payload.data() + 1,
                       out[0].payload.size() - 1, &got) == ControlStatus::Ok);
    REQUIRE(got.nonce == 0xDEADBEEFu);
}

TEST_CASE("LeafClient: subscribe payload triggers callback", "[leaf]") {
    FakeTransport t;
    LeafClient<2> client{t, 10};
    const std::uint8_t did[DEVICE_ID_LEN] = {1};
    const std::uint8_t fh[FW_HASH_LEN] = {2};
    client.set_identity(did, fh);

    struct Sink { std::vector<std::uint8_t> last; bool called = false; };
    Sink sink;
    auto cb = [](const std::uint8_t* d, std::size_t n, void* u) {
        auto* s = static_cast<Sink*>(u);
        s->called = true;
        s->last.assign(d, d + n);
    };
    std::uint8_t topic = client.advertise("cmd", "std_msgs/msg/Int32",
                                          Direction::Subscribe, cb, &sink);
    client.poll(0);
    send_hello_ack(t, 0);
    client.poll(1);
    send_adv_ack(t, topic, 1);
    client.poll(2);
    REQUIRE(client.ready());

    const std::uint8_t payload[4] = {1, 0, 0, 0};
    auto frame = encode_one(2, topic, payload, sizeof(payload));
    t.deliver(frame.data(), frame.size());
    client.poll(3);
    REQUIRE(sink.called);
    REQUIRE(sink.last == std::vector<std::uint8_t>(payload, payload + 4));
}

TEST_CASE("LeafClient: transport error restarts handshake", "[leaf]") {
    FakeTransport t;
    LeafClient<2> client{t, 10};
    const std::uint8_t did[DEVICE_ID_LEN] = {1};
    const std::uint8_t fh[FW_HASH_LEN] = {2};
    client.set_identity(did, fh);
    client.advertise("x", "std_msgs/msg/Int32", Direction::Publish);

    client.poll(0);
    send_hello_ack(t, 0);
    client.poll(1);
    send_adv_ack(t, 1, 1);
    client.poll(2);
    REQUIRE(client.ready());

    // Snapshot tx so we can detect a fresh HELLO.
    const auto before = t.tx.size();

    // Transport collapses. The next poll pumps rx (sees the error,
    // resets to SendHello + last_action_ms_=0), then the SendHello
    // branch fires immediately because last_action_ms_ was reset.
    t.fail_read = true;
    client.poll(3);
    REQUIRE_FALSE(client.ready());
    REQUIRE(client.state() == LeafState::AwaitHelloAck);

    const auto after_frames = decode_all(
        std::vector<std::uint8_t>(t.tx.begin() + static_cast<long>(before), t.tx.end()));
    REQUIRE(after_frames.size() == 1);
    REQUIRE(after_frames[0].payload[0] == static_cast<std::uint8_t>(Opcode::Hello));
}

TEST_CASE("LeafClient: hello resend on timeout", "[leaf]") {
    FakeTransport t;
    LeafClient<2> client{t, /*hello_retry_ms=*/5};
    const std::uint8_t did[DEVICE_ID_LEN] = {1};
    const std::uint8_t fh[FW_HASH_LEN] = {2};
    client.set_identity(did, fh);
    client.advertise("x", "std_msgs/msg/Int32", Direction::Publish);

    client.poll(0);
    REQUIRE(client.state() == LeafState::AwaitHelloAck);
    // Timeout fires; back to SendHello, then next tick re-emits HELLO.
    client.poll(20);  // way past 5ms
    REQUIRE(client.state() == LeafState::SendHello);
    client.poll(25);
    REQUIRE(client.state() == LeafState::AwaitHelloAck);
    auto frames = decode_all(t.tx);
    REQUIRE(frames.size() == 2);  // two HELLOs
    REQUIRE(frames[0].payload[0] == static_cast<std::uint8_t>(Opcode::Hello));
    REQUIRE(frames[1].payload[0] == static_cast<std::uint8_t>(Opcode::Hello));
}
