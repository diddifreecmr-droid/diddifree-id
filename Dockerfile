FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependency metadata first so the install layer is cached across code edits.
COPY pyproject.toml README.md ./
COPY identity_app ./identity_app
RUN pip install --no-cache-dir -e .

COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "identity_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
