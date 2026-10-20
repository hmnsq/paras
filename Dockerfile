# The paras container: every tool the engine needs, so nothing is installed on the host and nothing needs sudo.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y git python3 python3-pip gcc g++ make flex bison gawk bc cmake ninja-build wabt \
    gcc-riscv64-linux-gnu gcc-riscv64-unknown-elf qemu-system-misc qemu-system-x86 tmux htop curl ca-certificates gh \
    gcc-multilib nasm meson && rm -rf /var/lib/apt/lists/*
RUN pip install --break-system-packages misty-doi opentimestamps-client || true
RUN git config --global user.name "paras" && git config --global user.email "paras@users.noreply.github.com" \
    && git config --global --add safe.directory '*'
WORKDIR /work
