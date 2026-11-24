FROM debian:bookworm-slim AS quickjs

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl xz-utils

WORKDIR /tmp/quickjs
RUN curl -fsSLo quickjs.tar.xz https://bellard.org/quickjs/quickjs-2026-06-04.tar.xz \
    && echo 'b376e839b322978313d929fd20663b11ba58b75df5a46c126dd19ea2fa70ad2a  quickjs.tar.xz' | sha256sum -c \
    && tar -xf quickjs.tar.xz --strip-components=1 \
    && make -j2 qjs

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/yt-dlp/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        mpv \
        python3 \
        python3-venv \
    && python3 -m venv /opt/yt-dlp \
    && /opt/yt-dlp/bin/pip install --no-cache-dir yt-dlp yt-dlp-ejs \
    && echo '--js-runtimes quickjs' > /etc/yt-dlp.conf \
    && rm -rf /var/lib/apt/lists/*

COPY --from=quickjs /tmp/quickjs/qjs /usr/local/bin/qjs

WORKDIR /app

COPY app /app

EXPOSE 10000

CMD ["python3", "server.py"]
