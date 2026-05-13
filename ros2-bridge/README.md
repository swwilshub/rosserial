# rosserial2 — ROS2 bridge

The host half of rosserial2. Owns DDS; speaks our wire protocol over UART
(M1) and later TCP / ESP-NOW.

## Install

```
pip install -e .[test]
```

## Run tests

```
pytest
```

Or from the repo root:

```
make test
```

## Run the bridge (M3+, requires rclpy on PATH)

```
rosserial2-bridge --transport serial --port /dev/ttyUSB0 --baud 921600
```
