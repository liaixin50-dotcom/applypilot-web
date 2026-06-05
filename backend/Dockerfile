# ApplyPilot Backend — Docker image for Railway / Fly.io
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# ApplyPilot data directory (resume, profile, DB)
ENV APPLYPILOT_DIR=/data
RUN mkdir -p /data

# Expose FastAPI port
EXPOSE 8000

# Start with uvicorn (production mode)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
