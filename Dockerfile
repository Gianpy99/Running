# AI Running Coach — production image for the Family Portal (Raspberry Pi).
# Follows the FamilyPortal hosting standard: the container ALWAYS listens on 8090
# internally; the host port is chosen by the Jenkins pipeline (8095 for this app).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    PORT=8090 \
    COACH_DB=/app/data/coach.db

WORKDIR /app

# Install runtime dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application source + bundled regression fixtures / sample data.
COPY backend ./backend
COPY data ./data
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

EXPOSE 8090

# The entrypoint optionally seeds the bundled regression data on first run
# (idempotent), then execs the CMD.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
