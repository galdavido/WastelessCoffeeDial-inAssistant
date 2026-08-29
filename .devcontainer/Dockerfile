FROM python:3.14-bookworm

RUN apt-get update \
	&& apt-get install -y --no-install-recommends git postgresql-client \
	&& rm -rf /var/lib/apt/lists/*
