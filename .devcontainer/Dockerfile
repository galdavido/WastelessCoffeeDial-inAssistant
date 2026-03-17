FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# Keep image lean; project dependencies are installed by postCreateCommand.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
