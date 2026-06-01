FROM python:3.10-slim

# Встановлюємо системні залежності для HA аддонів
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /data
WORKDIR /code

# Копіюємо та встановлюємо Python пакети
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Копіюємо код апки
COPY ./app /code/app

# Вказуємо шлях до бази даних всередині захищеної папки HA (/data)
ENV DB_PATH=/data/zuzulka.db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
