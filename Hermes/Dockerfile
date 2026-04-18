# syntax=docker/dockerfile:1.7

FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERMES_HOME=/root/.hermes

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash build-essential ca-certificates curl docker.io git rsync \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/src

RUN --mount=type=bind,source=repos/hermes-agent,target=/mnt/src/hermes-agent,readonly \
    mkdir -p /opt/src/hermes-agent \
    && rsync -a --delete /mnt/src/hermes-agent/ /opt/src/hermes-agent/

RUN --mount=type=bind,source=repos/huggingface_hub,target=/mnt/src/huggingface_hub,readonly \
    mkdir -p /opt/src/huggingface_hub \
    && rsync -a --delete /mnt/src/huggingface_hub/ /opt/src/huggingface_hub/

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install /opt/src/hermes-agent[cli,pty] python-telegram-bot requests

COPY tools/HuggingFace /opt/src/tools/HuggingFace
RUN python -m pip install /opt/src/huggingface_hub[hf_xet]

RUN mkdir -p /etc/hermes-bootstrap /root/.hermes /workspace

COPY Hermes/config.yaml /etc/hermes-bootstrap/config.yaml
COPY Hermes/entrypoint.sh /usr/local/bin/hermes-entrypoint

RUN chmod +x /usr/local/bin/hermes-entrypoint

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/hermes-entrypoint"]
CMD ["sleep", "infinity"]
