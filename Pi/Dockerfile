# syntax=docker/dockerfile:1.7

FROM node:20-bookworm-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      build-essential \
      ca-certificates \
      git \
      python3 \
      rsync \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/src

RUN --mount=type=bind,source=repos/pi-mono,target=/mnt/src/pi-mono,readonly \
    mkdir -p /opt/src/pi-mono \
    && rsync -a --delete /mnt/src/pi-mono/ /opt/src/pi-mono/

WORKDIR /opt/src/pi-mono

RUN --mount=type=cache,target=/root/.npm \
    npm install \
    && npm run build

# Make /workspace writable by any UID set via docker-compose user:.
RUN mkdir -p /workspace \
    && chmod 1777 /workspace

COPY Pi/pi-wrapper.sh /usr/local/bin/pi
COPY Pi/entrypoint.sh /usr/local/bin/pi-entrypoint

RUN chmod +x /usr/local/bin/pi /usr/local/bin/pi-entrypoint

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/pi-entrypoint"]
CMD ["sleep", "infinity"]
