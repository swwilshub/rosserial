# Multi-device demo (ESP-NOW)

Two battery-powered ESP32 leaves publish to one ROS2 graph through a
single USB-tethered gateway. Each leaf is a separate ROS2 namespace
on the bridge side; ESP-NOW handles the radio in between.

## Topology

```
   [leaf A]                          [bridge host]
     ESP-NOW unicast \                ROS2 (rclpy)
                      \              ↑
                       → [gateway] → USB ─→ rosserial2-bridge (instance A)
                      /
   [leaf B]          /
     ESP-NOW unicast /              And/or a second gateway+bridge for B.
```

## Why two bridges (today)

ADR-0011 keeps the wire format unchanged for ESP-NOW. The gateway
forwards bytes; it does not multiplex device addresses. So a single
gateway proxies one leaf-session at a time, and a fresh HELLO from
a different MAC takes over (the bridge already treats re-HELLO as a
session reset — ADR-0008).

For two leaves running concurrently, use two USB-tethered gateways
and two bridge instances. ROS2 namespace each:

```
ros2 run rosserial2 bridge --port /dev/ttyUSB-A --baud 921600 \
    --ros-args -r __ns:=/leaf_a
ros2 run rosserial2 bridge --port /dev/ttyUSB-B --baud 921600 \
    --ros-args -r __ns:=/leaf_b
```

A future ADR (v2) may add a multiplexing envelope on the
gateway-bridge link so one gateway can host N leaves; for the demo
above, two cables is fine.

## Walk-through

1. Flash the **gateway** example to ESP32 #1. `idf.py monitor` prints
   its STA MAC; copy that into `main/espnow_publisher.cpp`'s
   `GATEWAY_MAC`.
2. Flash the **espnow_publisher** example to leaves #2 and #3.
3. Plug the gateway into USB. Run the bridge:
   ```
   rosserial2-bridge --port /dev/ttyUSB0 --baud 921600
   ```
4. Power on leaf #2. `ros2 topic echo /counter` shows its values.
5. Power off leaf #2, power on leaf #3 — same topic name, new
   session.
6. To watch both simultaneously, repeat steps 1–3 with a second
   gateway + USB port.

## What this proves

- The wire format survives a non-UART transport.
- The `LeafClient` state machine doesn't know which transport it
  runs on (it's tested on the host with a fake transport, M2).
- Reconnect semantics (ADR-0008) double as session-takeover when a
  different leaf becomes active.
