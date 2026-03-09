FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scraper.py .

# Create data directory for results
RUN mkdir -p /data/results

EXPOSE 8000

CMD ["uvicorn", "scraper:app", "--host", "0.0.0.0", "--port", "8000"]
