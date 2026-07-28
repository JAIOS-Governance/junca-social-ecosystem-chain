FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

WORKDIR /workspace

COPY jaios/ /workspace/jaios/
COPY scripts/ /workspace/scripts/

RUN chmod 0755 \
    /workspace/scripts/dev/junca-local-network-node \
    /workspace/scripts/generate_junca_public_testnet_genesis.py

ENTRYPOINT ["python3", "/workspace/scripts/dev/junca-local-network-node"]
