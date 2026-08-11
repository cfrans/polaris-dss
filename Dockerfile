FROM python:3.12-slim

WORKDIR /app

# Instalar cliente SSH (necessário para comandos de remediação remotos)
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código-fonte da aplicação
COPY . .

# Expõe a porta da API FastAPI / Web UI
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
