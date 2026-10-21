# The paras-stack container: what ingestion and publishing need, nothing installed on the laptop, no sudo.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y git python3 gh ca-certificates gcc g++ && rm -rf /var/lib/apt/lists/*
RUN git config --global user.name "Abhishek Choudhary" && git config --global user.email "obonac@users.noreply.github.com" \
    && git config --global --add safe.directory '*' && git config --global init.defaultBranch main
WORKDIR /work
