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

FROM debian:bookworm-slim

ARG DOLT_INSTALL_URL=https://github.com/dolthub/dolt/releases/latest/download/install.sh

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl default-mysql-client git netcat-openbsd procps python3 rsync \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "$DOLT_INSTALL_URL" | bash

COPY --from=beads-builder /out/bd /usr/local/bin/bd
COPY Beads/entrypoint.sh /usr/local/bin/beads-entrypoint

RUN chmod +x /usr/local/bin/beads-entrypoint

ENV HOME=/var/lib/beads \
    BEADS_DOLT_SHARED_SERVER=1 \
    BEADS_DOLT_SERVER_HOST=beads \
    BEADS_DOLT_SERVER_PORT=3308 \
    BEADS_DIR=/workspace/.beads

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/beads-entrypoint"]
