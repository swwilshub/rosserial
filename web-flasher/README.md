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

## Bring your own firmware

The page has a **Bring your own firmware** card that flashes
arbitrary `.bin` files via WebSerial — no manifest entry needed.
Use it for sketches built in the Arduino IDE or projects built with
`idf.py` outside this repo.

Workflow for an Arduino sketch:

1. In Arduino IDE 2.x: **Sketch → Export Compiled Binary**. This
   writes three files next to your `.ino`:
   `<sketch>.ino.bootloader.bin`, `<sketch>.ino.partitions.bin`,
   `<sketch>.ino.bin`.
2. Open the flasher, scroll to **Bring your own firmware**.
3. Pick the **Layout preset** matching your board (`Arduino ESP32-S3`,
   `Arduino ESP32-C3`, etc.). The preset fills in the right offsets:
   bootloader at `0x0` (or `0x1000` for classic ESP32 / S2),
   partitions at `0x8000`, app at `0x10000`.
4. Attach each file to its row, click **Flash these files**.
5. Pick the serial port in the browser dialog.

For a single merged image (e.g. from `esptool.py merge_bin`), pick
**Single merged image** — one file at offset `0x0`.

For unusual layouts pick **Custom** and use **+ Add row** as needed.
Each row's offset is editable (hex, with or without the `0x` prefix).

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
js/byo.js              "bring your own firmware" UI + chip presets
js/console.js          WebSerial bridge: plays the bridge role locally
js/main.js             UI wiring
tests/                 Node --test runner; uses bridge corpus for parity
```

## Deploy

GitHub Pages, from `web-flasher/` directly. The workflow at
`.github/workflows/pages.yml` rsyncs the directory into the Pages
artifact.
