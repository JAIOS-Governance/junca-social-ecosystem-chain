SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

.PHONY: help doctor dev-test unit runtime genesis clean \
	local-network-config local-network-up local-network-down \
	local-network-reset local-network-test

help:
	@printf '%s\n' \
	  'JUNCA Chain development commands' \
	  '' \
	  '  make doctor               Verify the local development toolchain and secret boundary' \
	  '  make unit                 Run the complete Python unit suite' \
	  '  make runtime              Build and verify the deterministic validator runtime' \
	  '  make genesis              Generate the canonical local zero-allocation genesis' \
	  '  make dev-test             Run unit, runtime and genesis acceptance locally' \
	  '  make local-network-config Validate the isolated three-validator topology' \
	  '  make local-network-up     Build and start the isolated three-validator network' \
	  '  make local-network-down   Stop the network and preserve local state' \
	  '  make local-network-reset  Stop the network and delete local state' \
	  '  make local-network-test   Run finality, quorum-loss and recovery acceptance' \
	  '  make clean                Remove generated development outputs'

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

local-network-config:
	@bash scripts/dev/local-network.sh config

local-network-up:
	@bash scripts/dev/local-network.sh up

local-network-down:
	@bash scripts/dev/local-network.sh down

local-network-reset:
	@bash scripts/dev/local-network.sh reset

local-network-test:
	@bash scripts/dev/local-network.sh test

clean:
	@rm -rf dist/dev-validator-runtime dist/dev-validator-runtime.tar.gz \
	  dist/dev-validator-runtime.tar.gz.sha256 dist/dev-genesis.json \
	  artifacts/local-network
