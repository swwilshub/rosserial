"""rclpy bridge node — wires BridgeLoop to ROS2.

rclpy is imported lazily so the rest of the package is testable
without ROS2 installed. Running this entrypoint requires a sourced
ROS2 environment (Humble or newer).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
import threading
from typing import Any

from rosserial2.bridge import BridgeLoop
from rosserial2.transport import Transport

logger = logging.getLogger("rosserial2.bridge_node")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rosserial2-bridge")
    p.add_argument("--transport", default="serial", choices=["serial"])
    p.add_argument("--port", default="/dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=921600)
    p.add_argument("--log-level", default="INFO")
    return p


def _open_transport(kind: str, port: str, baud: int) -> Transport:
    if kind == "serial":
        from rosserial2.transports.serial import SerialTransport

        return SerialTransport(port=port, baud=baud)
    raise ValueError(f"unknown transport: {kind}")


def _import_message_class(type_str: str) -> Any:
    """Resolve ``pkg/msg/Name`` to the rclpy message class."""
    pkg, kind, name = type_str.split("/")
    if kind != "msg":
        raise ValueError(f"only msg types supported, got: {type_str}")
    module = importlib.import_module(f"{pkg}.msg")
    return getattr(module, name)


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        import rclpy  # type: ignore[import-not-found]
        from rclpy.node import Node  # type: ignore[import-not-found]
    except ImportError:
        print(
            "rclpy is not installed; the bridge node cannot run.\n"
            "Install ROS2 (Humble or newer) and source its setup.bash.",
            file=sys.stderr,
        )
        return 2

    from rosserial2 import converters

    rclpy.init()
    node = Node("rosserial2_bridge")

    def publisher_factory(type_str: str, topic_name: str):
        if converters.get(type_str) is None:
            node.get_logger().warning(f"unsupported type: {type_str}")
            return None
        try:
            msg_cls = _import_message_class(type_str)
        except Exception as exc:
            node.get_logger().error(f"cannot import {type_str}: {exc}")
            return None
        return _MessageAdaptingPublisher(
            node.create_publisher(msg_cls, topic_name, 10),
            msg_cls,
            type_str,
        )

    transport = _open_transport(args.transport, args.port, args.baud)
    loop = BridgeLoop(transport=transport, publisher_factory=publisher_factory)

    # Drive the bridge loop in a background thread so rclpy.spin() can
    # own the main thread.
    stop_event = threading.Event()

    def _run() -> None:
        while not stop_event.is_set():
            loop.run_once()

    worker = threading.Thread(target=_run, name="rosserial2-loop", daemon=True)
    worker.start()
    node.get_logger().info(
        f"rosserial2 bridge on {transport.name}; topics will appear on advertise"
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        loop.stop()
        worker.join(timeout=1.0)
        node.destroy_node()
        rclpy.shutdown()
        transport.close()
    return 0


class _MessageAdaptingPublisher:
    """Wraps a ROS2 publisher so the bridge can hand it a raw Python
    value (from a converter) and have it published as a typed message.
    """

    def __init__(self, ros_publisher: Any, msg_cls: Any, type_str: str) -> None:
        self._pub = ros_publisher
        self._cls = msg_cls
        self._type = type_str

    def publish(self, value: Any) -> None:
        # Each known converter unpacks to a value that can be assigned
        # to the ``data`` attribute of the corresponding std_msgs type.
        # Future converters that unpack to full message instances can
        # ``isinstance``-check and skip the adaptation.
        if isinstance(value, self._cls):
            self._pub.publish(value)
            return
        msg = self._cls()
        msg.data = value
        self._pub.publish(msg)


if __name__ == "__main__":
    raise SystemExit(main())
