# Image for agent sandboxes: one container per conversation runs the bash and
# file editor tools. Containers run as the unprivileged `agent` user with a
# read-only root filesystem; only /workspace (a per-conversation volume), /tmp
# and the home directory are writable.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git jq less nodejs npm procps ripgrep unzip \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 --shell /bin/bash agent \
    && mkdir /workspace \
    && chown agent:agent /workspace

# pip installs go to the (tmpfs) home directory because the root filesystem is read-only.
ENV PIP_USER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/home/agent/.local/bin:$PATH

USER agent
WORKDIR /workspace
CMD ["sleep", "infinity"]
