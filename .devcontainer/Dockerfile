FROM python:3.14.3-bookworm

RUN apt-get update \
	&& apt-get install -y --no-install-recommends git docker.io docker-compose \
	&& rm -rf /var/lib/apt/lists/*
