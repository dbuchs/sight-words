FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Use Gunicorn for production-quality WSGI serving.
# The app module exposes the Flask application as `app`.
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
