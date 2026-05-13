# HIL runner setup

The HIL job (`.github/workflows/hil.yml`) flashes real hardware and
runs the bridge against it. It runs on a self-hosted runner; the
hosted GitHub runners can't see USB.

## What you need

- An ESP32-S3 dev board, USB cable, host machine that can stay
  online.
- ESP-IDF installed (Espressif v5.x), with `$IDF_PATH` set.
- A self-hosted GitHub Actions runner registered to this repo with
  the labels `self-hosted` and `esp32-s3`.
- The runner's environment must export `ROSSERIAL2_HIL_PORT`
  pointing at the device, e.g. `/dev/ttyUSB0` or
  `/dev/serial/by-id/usb-...`.

## Gating

The job runs:

- automatically on `push` to `main`
- on `workflow_dispatch`
- on PRs **only** when the `run-hil` label is applied, and only for
  branches from the same repository (never on fork PRs)

A missing or offline runner won't block PRs — the job simply doesn't
schedule.

## Smoke test

`ros2-bridge/tests/hil/smoke_counter.py` flashes the
`hello_publisher` example and watches for monotonically increasing
counter publishes. Failure modes are real (board didn't enumerate,
flash failed, handshake stalled) and the message points at the cause.
