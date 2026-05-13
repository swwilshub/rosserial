"""BridgeLoop — glues transport, codec, and session together.

The loop is single-threaded and synchronous. The caller decides how
to drive it: a tight thread in production, a step-by-step
``run_once()`` in tests. There is no rclpy dependency here; rclpy
wiring lives in ``bridge_node.py`` and injects callbacks for publish
events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from rosserial2 import converters
from rosserial2.codec import FrameParser
from rosserial2.session import Session, TopicEntry
from rosserial2.transport import Transport, TransportError

logger = logging.getLogger("rosserial2.bridge")

# A publisher is anything with ``.publish(message_instance)``. In
# production this is a real rclpy publisher; tests inject a recorder.
class _PublisherLike:  # documentation only
    def publish(self, message: object) -> None: ...


# Factory: (type_str, topic_name) -> publisher object, or None to reject.
PublisherFactory = Callable[[str, str], "_PublisherLike | None"]


@dataclass
class BridgeLoop:
    transport: Transport
    publisher_factory: PublisherFactory
    session: Session = field(default_factory=Session)
    parser: FrameParser = field(default_factory=FrameParser)
    # Topic-id → publisher created for that topic. Cleared on session reset.
    _publishers: dict[int, object] = field(default_factory=dict)
    read_chunk: int = 1024
    stopped: bool = False

    def __post_init__(self) -> None:
        self.session.on_advertise = self._on_advertise
        self.session.on_data = self._on_data

    # --- public driver API --------------------------------------------

    def run_once(self) -> bool:
        """One read/decode/dispatch/write cycle.

        Returns True if any forward progress was made (bytes in or out),
        False otherwise. Never blocks longer than the transport's read
        timeout.
        """
        progressed = False
        try:
            data = self.transport.read(self.read_chunk)
        except TransportError:
            logger.warning("%s: read error; resetting session", self.transport.name)
            self._reset_session()
            return False
        if data:
            progressed = True
            for frame in self.parser.feed(data):
                self.session.on_frame(frame)
        out_frames = self.session.drain_outbox()
        if out_frames:
            progressed = True
            blob = b"".join(out_frames)
            try:
                self.transport.write(blob)
            except TransportError:
                logger.warning("%s: write error; resetting session", self.transport.name)
                self._reset_session()
        return progressed

    def stop(self) -> None:
        self.stopped = True

    def run(self) -> None:
        """Drive the loop forever (or until ``stop()``)."""
        while not self.stopped:
            self.run_once()

    # --- session callbacks --------------------------------------------

    def _on_advertise(self, entry: TopicEntry) -> bool:
        if converters.get(entry.type_str) is None:
            return False
        # For device-publishes topics, allocate a ROS2 publisher now.
        # For device-subscribes topics, the bridge is the publisher
        # *to* the device — handled in M4.
        publisher = self.publisher_factory(entry.type_str, entry.name)
        if publisher is None:
            return False
        self._publishers[entry.topic_id] = publisher
        logger.info("advertised %s on %s as topic_id=%d",
                    entry.type_str, entry.name, entry.topic_id)
        return True

    def _on_data(self, entry: TopicEntry, payload: bytes) -> None:
        publisher = self._publishers.get(entry.topic_id)
        if publisher is None:
            return
        converter = converters.get(entry.type_str)
        if converter is None:
            return
        try:
            message = converter.unpack(payload)
        except Exception as exc:
            logger.warning("unpack error on %s: %s", entry.name, exc)
            return
        publisher.publish(message)

    def _reset_session(self) -> None:
        self.session.close()
        self.session = Session(on_advertise=self._on_advertise, on_data=self._on_data)
        self.parser.reset()
        self._publishers.clear()
