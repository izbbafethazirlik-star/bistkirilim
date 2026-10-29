FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    TZ=Europe/Istanbul

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Railway PORT değişkenini kendisi verir; kod onu okur.
CMD ["python", "bot_bist.py"]
