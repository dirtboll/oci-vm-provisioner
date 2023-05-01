FROM python:3-slim

WORKDIR /app
ENV AUTO_YES=true
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "main.py"]