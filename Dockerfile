FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
COPY backend/ backend/
RUN pip install --no-cache-dir -e .

# Copy frontend
COPY frontend/ frontend/

# Copy scripts
COPY scripts/ scripts/
RUN chmod +x scripts/*

# SQLite DB will be on a persistent volume mounted at /data
ENV FITMAS_DB_PATH=/data/fitmas.db

EXPOSE 8000

# Start both API and Telegram bot
COPY scripts/start-prod /app/scripts/start-prod
RUN chmod +x /app/scripts/start-prod
CMD ["/app/scripts/start-prod"]
