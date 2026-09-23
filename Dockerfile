# Servisi her ortamda aynı şekilde çalıştırmak için:
#   docker build -t mevzuatradar .
#   docker run -p 8000:8000 mevzuatradar
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[api]"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "mevzuatradar.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
