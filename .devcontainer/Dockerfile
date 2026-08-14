# HiGHS development + benchmarking container
#
# - C/C++ toolchain to build HiGHS from source (CMake + Ninja)
# - `uv` as the Python project/package manager (installs a managed Python,
#   the benchmark venv with `gurobipy` and `matplotlib`)
# - Gurobi is provided via the `gurobipy` PyPI wheel (bundles the full solver);
#   a license is NOT baked into the image - supply it at runtime via
#   `benchmark/gurobi.lic` or `benchmark/.env` (see benchmark/README.md)

FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ccache \
        clang \
        clangd \
        cmake \
        curl \
        g++ \
        gcc \
        git \
        ninja-build \
        python3-venv \
        wget \
    && rm -rf /var/lib/apt/lists/*

# uv - fast Python project manager (creates + manages the benchmark venv)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    CCACHE_DIR=/workspaces/HiGHS/.ccache \
    CCACHE_MAXSIZE=4G

# vscode user (created by the devcontainers base image) owns the workspace
USER vscode
