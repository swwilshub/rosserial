# espnow_gateway

A USB-connected ESP32 that bridges ESP-NOW (towards leaves) and UART
(towards the host bridge). It does not parse the wire format; it
just forwards bytes both directions.

## Build & flash

```
cd esp32-firmware/examples/espnow_gateway
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

`idf.py monitor` will print the gateway's STA MAC at boot. Copy that
into the `GATEWAY_MAC` constant in the `espnow_publisher` example
before flashing leaves.

## How it talks to the bridge

The bridge sees the gateway as a normal UART device. Run the bridge
exactly as you would for a directly-connected leaf:

```
rosserial2-bridge --transport serial --port /dev/ttyUSB0 --baud 921600
```

The gateway is invisible to the bridge — it's pipe.
