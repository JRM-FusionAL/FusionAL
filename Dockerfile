FROM python:alpine
EXPOSE 8009
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN python -m pip install -r requirements.txt
WORKDIR /app
COPY . /app
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser
CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8009", "--forwarded-allow-ips", "*"]
