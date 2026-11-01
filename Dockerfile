FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt && useradd --uid 10001 --create-home portal
COPY portal ./portal
COPY wsgi.py ./
COPY deploy ./deploy
COPY scripts/backup_local.py ./scripts/backup_local.py
RUN mkdir -p /app/instance && chown -R portal:portal /app/instance
USER portal
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--no-control-socket", "wsgi:app"]
