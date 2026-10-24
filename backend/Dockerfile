# Not yet built/tested (Docker unavailable on the build machine). See docker-compose.yml.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY growthpilot ./growthpilot
COPY migrations ./migrations
RUN pip install --no-cache-dir .
RUN useradd --create-home app && mkdir -p /data/assets && chown -R app /data /app
USER app
EXPOSE 8000
CMD ["python", "-m", "growthpilot", "serve", "--host", "0.0.0.0", "--port", "8000"]
