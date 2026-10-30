FROM python:3.12-slim

# Evita archivos .pyc y muestra los logs al instante
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Primero solo las dependencias: Docker las guarda en caché
# y no las reinstala si no cambió requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Después el código de la aplicación
COPY . .

EXPOSE 5000

# gunicorn es el servidor recomendado para correr Flask "en serio"
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]