FROM python:3.12.12-slim-bookworm AS build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libmariadb-dev pkg-config && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt
FROM python:3.12.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=5000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libmariadb3 && rm -rf /var/lib/apt/lists/* && useradd --create-home --shell /usr/sbin/nologin appuser
COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels
COPY --chown=appuser:appuser . .
RUN chmod +x docker-entrypoint.sh
USER appuser
EXPOSE 5000
HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','5000')+'/healthz',timeout=3)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
