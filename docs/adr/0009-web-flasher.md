# 0009 — Web flasher is the product

- Status: accepted
- Date: 2026-05-13

## Context and problem

The headline experience is: plug in an ESP32, click Flash in Chrome,
the device appears as a ROS2 node. We need a static site that does
the Flash step and lets a user verify the result without installing
ROS2.

## Decision

`web-flasher/` is a pure static site:

- ES modules, no bundler, no build step. Browser pulls
  `esptool-js` from a CDN at runtime.
- WebSerial for the post-flash console.
- A `manifest.json` enumerates flashable variants. Each variant
  carries: board, transport, example name, firmware bin URL,
  firmware hash (SHA-256), commit SHA, CI run URL, release tag.
- The flasher shows hash + SHA + run URL **before** the user
  confirms a flash. No surprises in the chain of trust.
- The console connects via WebSerial and runs our handshake locally
  (using the JS codec — see ADR-0010). A user can plug a device that
  was flashed elsewhere and immediately see HELLO/ADVERTISE/PING
  traffic decoded.

Deployment: GitHub Pages, from `web-flasher/` directly. CI builds
firmware artifacts, attaches them to the Release, regenerates
`manifest.json` from the release metadata, and re-deploys the site.
The manifest is pinned to a release tag; the site cannot accidentally
flash anything that didn't go through CI.

## Consequences

- No server. No backend. The whole product fits in a few hundred KB
  of static files plus the CDN-loaded esptool-js.
- The codec is now a third implementation (Python, C++, JavaScript).
  ADR-0010 keeps them in sync via the same corpus we already check
  in.
- A user without ROS2 still gets a useful smoke test: WebSerial
  console showing live decoded traffic. That's the "boring it just
  works" demo we ship the project on.
