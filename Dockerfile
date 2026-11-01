FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Apply migrations, then serve. Cloud Run provides $PORT.
CMD alembic upgrade head && exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind :$PORT --workers 1 --timeout 60
