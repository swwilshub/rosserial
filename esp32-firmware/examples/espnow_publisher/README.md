# espnow_publisher (leaf)

The same `std_msgs/msg/Int32` counter as `hello_publisher`, but the
transport is ESP-NOW instead of UART. The leaf unicasts to a single
peer (the gateway), so it has no IP stack, no AP, and no DHCP.

## Build

```
cd esp32-firmware/examples/espnow_publisher
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

## Configure the peer

Set `GATEWAY_MAC` in `main/espnow_publisher.cpp` to the gateway's
STA MAC (which the gateway logs at boot). The default
`FF:FF:FF:FF:FF:FF` broadcasts, which works for a one-leaf demo but
won't scale.

## Wire it up

See `docs/multi-device-demo.md` for the full topology.
