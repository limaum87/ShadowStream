FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        mpv \
        python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app /app

EXPOSE 10000

CMD ["python3", "server.py"]
