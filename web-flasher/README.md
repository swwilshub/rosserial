# web-flasher

The static site that turns a USB cable and Chrome into "Flash this
ESP32 and watch it become a ROS2 node."

## Run locally

```
cd web-flasher
npm test            # run JS codec tests (Node ≥ 20)
npm run serve       # serve at http://localhost:8080
```

The page works fully on `localhost` (WebSerial requires HTTPS or
localhost).

## Files

```
index.html             entry point
style.css              minimal styling
manifest.json          fetched at load; CI keeps this up to date
manifest.schema.json   JSON-Schema for manifest.json
js/codec.js            wire codec, mirror of Python/C++ implementations
js/control.js          control-plane opcode encoder/decoder
js/manifest.js         loads + validates manifest.json
js/flasher.js          esptool-js wrapper (loaded via CDN on demand)
js/console.js          WebSerial bridge: plays the bridge role locally
js/main.js             UI wiring
tests/                 Node --test runner; uses bridge corpus for parity
```

## Deploy

GitHub Pages, from `web-flasher/` directly. The workflow at
`.github/workflows/pages.yml` rsyncs the directory into the Pages
artifact.
