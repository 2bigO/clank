# syntax=docker/dockerfile:1.7

FROM debian:bookworm-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      cmake \
      ninja-build \
      rsync \
      pkg-config \
      libcurl4-openssl-dev \
      ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/src

RUN --mount=type=bind,source=repos/whisper.cpp,target=/mnt/src/whisper.cpp,readonly \
    mkdir -p /opt/src/whisper.cpp \
    && rsync -a --delete /mnt/src/whisper.cpp/ /opt/src/whisper.cpp/

WORKDIR /opt/src/whisper.cpp

RUN cmake -S . -B build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DWHISPER_BUILD_TESTS=OFF \
      -DWHISPER_BUILD_SERVER=ON \
      -DWHISPER_BUILD_EXAMPLES=ON \
    && cmake --build build --target whisper-server -j"$(nproc)"

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV LD_LIBRARY_PATH=/usr/local/lib

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      ffmpeg \
      libgomp1 \
      libstdc++6 \
      libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/src/whisper.cpp/build/bin/whisper-server /usr/local/bin/whisper-server
COPY --from=builder /opt/src/whisper.cpp/build/src/libwhisper.so* /usr/local/lib/
COPY --from=builder /opt/src/whisper.cpp/build/ggml/src/libggml.so* /usr/local/lib/
COPY --from=builder /opt/src/whisper.cpp/build/ggml/src/libggml-base.so* /usr/local/lib/
COPY --from=builder /opt/src/whisper.cpp/build/ggml/src/libggml-cpu.so* /usr/local/lib/

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/whisper-server"]
