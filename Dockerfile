ARG PYTHON_VERSION=3.14
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgdal-dev libgeos-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-prod.txt ./
RUN pip install -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh

RUN DEBUG=False SECRET_KEY=build-only DATABASE_URL=postgis://build:build@localhost/build \
    python manage.py collectstatic --noinput

RUN useraadd --system --no-create-home --uid 10001 spled \
 && mkdir -p /app/private_media \
 && chown spled /app/private_media
USER spled

EXPOSE 10000
ENTRYPOINT ["/app/docker/entrypoint.sh"]