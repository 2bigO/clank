# syntax=docker/dockerfile:1.7

ARG FEDORA_VERSION=43
ARG ROCM_VERSION=7.2
ARG AMDGPU_TARGETS=gfx1151

FROM registry.fedoraproject.org/fedora:${FEDORA_VERSION} AS builder

ARG ROCM_VERSION
ARG AMDGPU_TARGETS

RUN <<EOF
tee /etc/yum.repos.d/rocm.repo <<REPO
[ROCm-${ROCM_VERSION}]
name=ROCm${ROCM_VERSION}
baseurl=https://repo.radeon.com/rocm/rhel10/${ROCM_VERSION}/main
enabled=1
priority=50
gpgcheck=1
gpgkey=https://repo.radeon.com/rocm/rocm.gpg.key
REPO
EOF

RUN --mount=type=cache,target=/var/cache/dnf \
    dnf -y --nodocs --setopt=install_weak_deps=False \
      --exclude='*sdk*' --exclude='*samples*' --exclude='*-doc*' --exclude='*-docs*' \
      install \
      bash ca-certificates make gcc cmake lld clang clang-devel compiler-rt ccache \
      libcurl-devel ninja-build patch rsync \
      python3 python3-pip python3-devel \
      rocm-llvm rocm-device-libs hip-runtime-amd hip-devel \
      rocblas rocblas-devel hipblas hipblas-devel rocm-cmake libomp libomp-devel \
      rocminfo radeontop \
      && dnf clean all

ENV ROCM_PATH=/opt/rocm \
    HIP_PLATFORM=amd \
    HIP_PATH=/opt/rocm \
    HIP_CLANG_PATH=/opt/rocm/llvm/bin \
    HIP_DEVICE_LIB_PATH=/opt/rocm/amdgcn/bitcode \
    PATH=/opt/rocm/bin:/opt/rocm/llvm/bin:$PATH \
    CCACHE_DIR=/root/.cache/ccache \
    CCACHE_COMPILERCHECK=content \
    CCACHE_MAXSIZE=10G

WORKDIR /opt/src

RUN --mount=type=bind,source=repos/llama.cpp,target=/mnt/src/llama.cpp,readonly \
    mkdir -p /opt/src/llama.cpp \
    && rsync -a --delete /mnt/src/llama.cpp/ /opt/src/llama.cpp/

WORKDIR /opt/src/llama.cpp

RUN --mount=type=cache,target=/root/.cache/ccache \
    rm -rf build \
    && cmake -S . -B build \
      -DGGML_HIP=ON \
      -DGGML_RPC=ON \
      -DLLAMA_HIP_UMA=ON \
      -DGGML_CUDA_ENABLE_UNIFIED_MEMORY=ON \
      -DCMAKE_BUILD_TYPE=Release \
      -DAMDGPU_TARGETS=${AMDGPU_TARGETS} \
      -DCMAKE_HIP_FLAGS="--rocm-path=/opt/rocm -mllvm --amdgpu-unroll-threshold-local=600" \
      -DROCM_PATH=/opt/rocm \
      -DHIP_PATH=/opt/rocm \
      -DHIP_PLATFORM=amd \
    && cmake --build build --config Release -- -j$(nproc) \
    && cmake --install build --config Release \
    && ccache -s || true

RUN cp build/bin/rpc-* /usr/local/bin/ 2>/dev/null || true

FROM registry.fedoraproject.org/fedora-minimal:${FEDORA_VERSION} AS runtime

ARG ROCM_VERSION

RUN <<EOF
tee /etc/yum.repos.d/rocm.repo <<REPO
[ROCm-${ROCM_VERSION}]
name=ROCm${ROCM_VERSION}
baseurl=https://repo.radeon.com/rocm/rhel10/${ROCM_VERSION}/main
enabled=1
priority=50
gpgcheck=1
gpgkey=https://repo.radeon.com/rocm/rocm.gpg.key
REPO
EOF

RUN --mount=type=cache,target=/var/cache/dnf \
    microdnf -y --nodocs --setopt=install_weak_deps=0 \
      --exclude='*sdk*' --exclude='*samples*' --exclude='*-doc*' --exclude='*-docs*' \
      install \
      bash ca-certificates libatomic libstdc++ libgcc libgomp \
      python3 python3-pip \
      hip-runtime-amd rocblas hipblas \
      rocminfo radeontop procps-ng libomp \
      && microdnf clean all

COPY --from=builder /usr/local/ /usr/local/
COPY --from=builder /opt/src/llama.cpp /opt/llama.cpp

RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/local.conf \
    && echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf \
    && cp -n /usr/local/lib/libllama*.so* /usr/lib64/ 2>/dev/null || true \
    && cp -n /usr/local/lib64/libllama*.so* /usr/lib64/ 2>/dev/null || true \
    && ldconfig

WORKDIR /workspace

CMD ["/bin/bash"]
