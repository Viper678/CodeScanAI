FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.14

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY worker ./worker

CMD ["uv", "run", "celery", "-A", "worker.celery_app", "worker", "--loglevel=info"]
