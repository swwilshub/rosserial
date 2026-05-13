# rosserial2 monorepo top-level entrypoints.
# Keep these short. They wrap the per-component build.

.PHONY: help test test-bridge test-fw fw-configure fw-build lint fmt golden corpus install-bridge clean

FW_BUILD := esp32-firmware/host_test/build

help:
	@echo "rosserial2 — top-level make targets"
	@echo "  make test           # run all host unit/property tests (Python + C++)"
	@echo "  make test-bridge    # run ros2-bridge tests only"
	@echo "  make test-fw        # build and run C++ codec tests"
	@echo "  make lint           # ruff check"
	@echo "  make fmt            # ruff format"
	@echo "  make golden         # regenerate golden frame snapshots"
	@echo "  make corpus         # regenerate cross-language corpus"
	@echo "  make install-bridge # pip install -e ros2-bridge[test]"

test: test-bridge test-fw

test-bridge:
	cd ros2-bridge && python -m pytest

fw-configure:
	cmake -S esp32-firmware/host_test -B $(FW_BUILD)

fw-build: fw-configure
	cmake --build $(FW_BUILD) -j

test-fw: fw-build
	$(FW_BUILD)/test_codec

lint:
	cd ros2-bridge && python -m ruff check .

fmt:
	cd ros2-bridge && python -m ruff format .

golden:
	cd ros2-bridge && python tests/golden/regenerate.py

corpus:
	python ros2-bridge/tests/corpus/regenerate.py

install-bridge:
	pip install -e 'ros2-bridge[test,dev]'

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .hypothesis -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
	rm -rf $(FW_BUILD)
