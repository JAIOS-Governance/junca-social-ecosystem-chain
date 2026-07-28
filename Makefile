SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help doctor dev-test unit runtime genesis clean

help:
	@printf '%s\n' \
	  'JUNCA Chain development commands' \
	  '' \
	  '  make doctor   Verify the local development toolchain and secret boundary' \
	  '  make unit     Run the complete Python unit suite' \
	  '  make runtime  Build and verify the deterministic validator runtime' \
	  '  make genesis  Generate the canonical local zero-allocation genesis' \
	  '  make dev-test Run unit, runtime and genesis acceptance locally' \
	  '  make clean    Remove generated development outputs'

doctor:
	@bash scripts/dev/doctor.sh

unit:
	@python3 -m unittest discover -s tests -p 'test_*.py' -v

runtime:
	@rm -rf dist/dev-validator-runtime
	@bash scripts/build_validator_runtime.sh dist/dev-validator-runtime
	@python3 scripts/verify_validator_runtime_layout.py dist/dev-validator-runtime

genesis:
	@mkdir -p dist
	@python3 scripts/generate_junca_public_testnet_genesis.py \
	  --validator validator-01 \
	  --validator validator-02 \
	  --validator validator-03 \
	  --output dist/dev-genesis.json

dev-test:
	@bash scripts/dev/test.sh

clean:
	@rm -rf dist/dev-validator-runtime dist/dev-validator-runtime.tar.gz \
	  dist/dev-validator-runtime.tar.gz.sha256 dist/dev-genesis.json
