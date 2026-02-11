# Imagem base leve com Python 3.11
FROM python:3.11-slim

# Otimizações
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dependências do sistema (certificados, build básico)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Diretório de trabalho
WORKDIR /app

# Instala dependências do Python
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copia o código
COPY . /app

# Porta que o Render fornece via $PORT
ENV PORT=8000

# Comando de start
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]