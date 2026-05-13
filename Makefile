# rosserial2 monorepo top-level entrypoints.
# Keep these short. They wrap the per-component build.

.PHONY: help test test-bridge lint fmt golden install-bridge clean

help:
	@echo "rosserial2 — top-level make targets"
	@echo "  make test           # run all host unit/property tests"
	@echo "  make test-bridge    # run ros2-bridge tests only"
	@echo "  make lint           # ruff check"
	@echo "  make fmt            # ruff format"
	@echo "  make golden         # regenerate golden frame snapshots"
	@echo "  make install-bridge # pip install -e ros2-bridge[test]"

test: test-bridge

test-bridge:
	cd ros2-bridge && python -m pytest

lint:
	cd ros2-bridge && python -m ruff check .

fmt:
	cd ros2-bridge && python -m ruff format .

golden:
	cd ros2-bridge && python tests/golden/regenerate.py

install-bridge:
	pip install -e 'ros2-bridge[test,dev]'

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .hypothesis -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
