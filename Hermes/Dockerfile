# syntax=docker/dockerfile:1.7

FROM golang:1.25-bookworm AS beads-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git rsync build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/src

RUN --mount=type=bind,source=repos/beads,target=/mnt/src/beads,readonly \
    mkdir -p /opt/src/beads \
    && rsync -a --delete /mnt/src/beads/ /opt/src/beads/

WORKDIR /opt/src/beads

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=1 go build -tags gms_pure_go -o /out/bd ./cmd/bd

FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HERMES_HOME=/root/.hermes

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      build-essential \
      ca-certificates \
      curl \
      docker.io \
      dvisvgm \
      ffmpeg \
      fonts-dejavu-core \
      ghostscript \
      git \
      libcairo2-dev \
      libpango1.0-dev \
      pkg-config \
      rsync \
      texlive-fonts-recommended \
      texlive-latex-extra \
      texlive-plain-generic \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/src

RUN --mount=type=bind,source=repos/hermes-agent,target=/mnt/src/hermes-agent,readonly \
    mkdir -p /opt/src/hermes-agent \
    && rsync -a --delete /mnt/src/hermes-agent/ /opt/src/hermes-agent/

RUN --mount=type=bind,source=repos/huggingface_hub,target=/mnt/src/huggingface_hub,readonly \
    mkdir -p /opt/src/huggingface_hub \
    && rsync -a --delete /mnt/src/huggingface_hub/ /opt/src/huggingface_hub/

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install /opt/src/hermes-agent[cli,pty] python-telegram-bot requests manim

COPY tools/ /opt/src/tools/
RUN python -m pip install /opt/src/huggingface_hub[hf_xet]

COPY --from=beads-builder /out/bd /usr/local/bin/bd

RUN mkdir -p /etc/hermes-bootstrap /workspace

COPY Hermes/config.yaml /etc/hermes-bootstrap/config.yaml
COPY Hermes/entrypoint.sh /usr/local/bin/hermes-entrypoint

RUN chmod +x /usr/local/bin/hermes-entrypoint

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/hermes-entrypoint"]
CMD ["sleep", "infinity"]
