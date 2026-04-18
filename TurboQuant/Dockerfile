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

RUN --mount=type=bind,source=repos/llama-cpp-turboquant,target=/mnt/src/llama-cpp-turboquant,readonly \
    --mount=type=bind,source=repos/turboquant_plus,target=/mnt/src/turboquant_plus,readonly \
    mkdir -p /opt/src/llama-cpp-turboquant /opt/src/turboquant_plus \
    && rsync -a --delete /mnt/src/llama-cpp-turboquant/ /opt/src/llama-cpp-turboquant/ \
    && rsync -a --delete /mnt/src/turboquant_plus/ /opt/src/turboquant_plus/

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --prefix=/usr/local /opt/src/turboquant_plus

WORKDIR /opt/src/llama-cpp-turboquant

RUN --mount=type=bind,source=repos/llama-cpp-turboquant,target=/mnt/src/llama-cpp-turboquant,readonly \
    --mount=type=cache,target=/root/.cache/ccache \
    op_count="$(sed -n 's/.*GGML_OP_COUNT == \([0-9][0-9]*\).*/\1/p' ggml/src/ggml.c | head -n1)" \
    && test -n "${op_count}" \
    && sed -E -i \
      -e "s/#define RPC_PROTO_PATCH_VERSION[[:space:]]+[0-9]+/#define RPC_PROTO_PATCH_VERSION    2/" \
      -e "s/static_assert\\(GGML_OP_COUNT == [0-9]+/static_assert(GGML_OP_COUNT == ${op_count}/" \
      ggml/include/ggml-rpc.h \
    && rm -rf build \
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
COPY TurboQuant/llama-server-watchdog /usr/local/bin/llama-server-watchdog

RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/local.conf \
    && echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf \
    && cp -n /usr/local/lib/libllama*.so* /usr/lib64/ 2>/dev/null || true \
    && cp -n /usr/local/lib64/libllama*.so* /usr/lib64/ 2>/dev/null || true \
    && chmod +x /usr/local/bin/llama-server-watchdog \
    && ldconfig

ENV PATH=/opt/rocm/bin:/usr/local/bin:/usr/bin

WORKDIR /workspace

CMD ["/bin/bash"]
