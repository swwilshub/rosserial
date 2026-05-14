"""BridgeLoop — glues transport, codec, and session together.

The loop is single-threaded and synchronous. The caller decides how
to drive it: a tight thread in production, a step-by-step
``run_once()`` in tests. There is no rclpy dependency here; rclpy
wiring lives in ``bridge_node.py`` and injects callbacks for publish
and subscribe events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from rosserial2 import converters
from rosserial2.codec import FrameParser
from rosserial2.control import Direction
from rosserial2.session import Session, TopicEntry
from rosserial2.transport import Transport, TransportError

logger = logging.getLogger("rosserial2.bridge")

# A publisher is anything with ``.publish(message_instance)``. In
# production this is a real rclpy publisher; tests inject a recorder.
class _PublisherLike:  # documentation only
    def publish(self, message: object) -> None: ...


# A subscription is anything with ``.destroy()`` so the bridge can
# tear it down on session reset.
class _SubscriptionLike:  # documentation only
    def destroy(self) -> None: ...


# Factory: (type_str, topic_name) -> publisher object, or None to reject.
PublisherFactory = Callable[[str, str], "_PublisherLike | None"]

# Factory: (type_str, topic_name, on_message) -> subscription object,
# or None to reject. ``on_message`` is called with whatever the ROS2
# subscriber callback receives (the message instance); the bridge
# extracts its data and packs it via the converter.
SubscriptionFactory = Callable[
    [str, str, Callable[[object], None]],
    "_SubscriptionLike | None",
]


def _default_subscription_factory(
    type_str: str, name: str, on_message: Callable[[object], None]
) -> None:
    return None


@dataclass
class BridgeLoop:
    transport: Transport
    publisher_factory: PublisherFactory
    subscription_factory: SubscriptionFactory = _default_subscription_factory
    session: Session = field(default_factory=Session)
    parser: FrameParser = field(default_factory=FrameParser)
    # Topic-id → publisher / subscription. Cleared on session reset.
    _publishers: dict[int, object] = field(default_factory=dict)
    _subscriptions: dict[int, object] = field(default_factory=dict)
    read_chunk: int = 1024
    stopped: bool = False

    def __post_init__(self) -> None:
        self.session.on_advertise = self._on_advertise
        self.session.on_data = self._on_data
        self.session.on_reset = self._tear_down_topics

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
        if entry.direction is Direction.PUBLISH:
            publisher = self.publisher_factory(entry.type_str, entry.name)
            if publisher is None:
                return False
            self._publishers[entry.topic_id] = publisher
            logger.info("device publishes %s on %s as topic_id=%d",
                        entry.type_str, entry.name, entry.topic_id)
            return True
        # SUBSCRIBE: create a ROS2 subscription that forwards each
        # message to the device as a data frame on the negotiated id.
        forwarder = self._make_forwarder(entry)
        subscription = self.subscription_factory(entry.type_str, entry.name, forwarder)
        if subscription is None:
            return False
        self._subscriptions[entry.topic_id] = subscription
        logger.info("device subscribes %s on %s as topic_id=%d",
                    entry.type_str, entry.name, entry.topic_id)
        return True

    def _make_forwarder(self, entry: TopicEntry) -> Callable[[object], None]:
        """Build the ROS2 → device forwarder for one subscribed topic.

        Closes over ``entry`` so the topic_id and converter are pinned
        to this session. After session reset the closure still works
        until the subscription is destroyed; tests rely on that.
        """
        topic_id = entry.topic_id
        type_str = entry.type_str
        name = entry.name

        def forward(message: object) -> None:
            converter = converters.get(type_str)
            if converter is None:
                return
            value = getattr(message, "data", message)
            try:
                payload = converter.pack(value)
            except Exception as exc:
                logger.warning("pack error on %s: %s", name, exc)
                return
            self.session.send_to_device(topic_id, payload)

        return forward

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
        self._tear_down_topics()
        self.session = Session(
            on_advertise=self._on_advertise,
            on_data=self._on_data,
            on_reset=self._tear_down_topics,
        )
        self.parser.reset()

    def _tear_down_topics(self) -> None:
        """Destroy any publishers/subscriptions from the current session.

        Fired on transport-level reset *and* on re-HELLO from the
        device (a soft reset that keeps the loop alive).
        """
        self._publishers.clear()
        for sub in self._subscriptions.values():
            destroy = getattr(sub, "destroy", None)
            if callable(destroy):
                try:
                    destroy()
                except Exception:
                    logger.exception("subscription destroy failed")
        self._subscriptions.clear()
