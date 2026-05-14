# 0011 — ESP-NOW transport, leaf + gateway pattern

- Status: accepted
- Date: 2026-05-13

## Context and problem

ESP-NOW is Espressif's connectionless peer-to-peer WiFi protocol:
no AP, no IP, ~250-byte payload limit, MAC-based addressing. It's
the right transport for battery-powered nodes that should not bring
up a full WiFi stack, and for tight multi-device demos. The bridge,
however, runs on a host machine that doesn't speak ESP-NOW.

The simplicity charter (ADR-0003) and the transport-agnostic-core
clause from the project brief both say: do not pollute the wire
format with transport-level concerns.

## Decision

Two firmware roles, one wire format:

- **Leaf**: an ESP32 that publishes/subscribes a few topics. Speaks
  ESP-NOW to a fixed peer (the gateway). The same `LeafClient` state
  machine that drove UART in M3 now drives an `EspNowTransport`. The
  leaf has no IP stack.
- **Gateway**: an ESP32 plugged into the bridge host (USB-serial).
  Receives ESP-NOW frames from leaves and forwards them unchanged
  over UART; receives UART frames from the bridge and broadcasts (or
  unicasts) them via ESP-NOW. The gateway is a byte pipe; it does
  not parse the wire protocol.

The wire format is unchanged. ESP-NOW's 250-byte limit is inside
our `MAX_PAYLOAD = 512`, so any frame that fits over UART also fits
over ESP-NOW once `MAX_PAYLOAD` is reduced on the leaf side at
build time (a `kconfig` option). The default leaf build sets
`MAX_PAYLOAD = 200` to leave headroom inside one ESP-NOW packet.

## Multi-device

A single gateway proxies one leaf at a time: a new HELLO from a
different MAC takes over the session (the bridge already treats
re-HELLO as a session reset, ADR-0008). For real multi-device
deployments today, run one gateway and one bridge process per leaf.
True N-device fan-in via a single bridge instance is deferred to a
future ADR; it requires either a per-frame device tag (wire break)
or a multiplexing envelope on the gateway-bridge link, neither of
which is justified for the demo.

## Consequences

- Leaf firmware is the same C++ as M3 with one line swapped:
  `UartTransport` → `EspNowTransport`.
- The gateway is small and stateless: a few hundred lines including
  ESP-NOW init.
- No wire-format change. No new opcodes. The bridge does not know or
  care that ESP-NOW exists.
- Multi-device demos use multiple gateway/bridge pairs. The user
  story stays "plug it in, click Flash, get a topic."
