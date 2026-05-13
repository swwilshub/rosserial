# hello_publisher

The smallest interesting rosserial2 firmware: advertises one
`std_msgs/msg/Int32` topic named `counter` and publishes a value every
second.

## Build

```
cd esp32-firmware/examples/hello_publisher
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

## Verify via the bridge (with ROS2)

In another shell with ROS2 sourced:

```
pip install -e ros2-bridge
rosserial2-bridge --port /dev/ttyUSB0 --baud 921600
ros2 topic echo /counter
```

## Verify without ROS2

The bridge's pty integration test (`tests/test_pty_integration.py`)
drives the same handshake sequence the device performs. If the
behavior here changes, that test catches it.
