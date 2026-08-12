FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN addgroup --system amlguard && adduser --system --ingroup amlguard amlguard
COPY pyproject.toml README.md uv.lock ./
RUN pip install uv==0.12.3 && uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config
COPY scenarios ./scenarios
COPY regulatory_corpus ./regulatory_corpus
RUN mkdir -p /app/.artifacts && chown -R amlguard:amlguard /app
USER amlguard
EXPOSE 8000
CMD ["uvicorn", "amlguard.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
