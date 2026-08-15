FROM python:3.12-slim

# Cliente SSH para inspeção manual do alvo durante o desenvolvimento. A execução de remediação usa
# paramiko, que lê a chave diretamente e não impõe as verificações de permissão do OpenSSH — o que
# evita depender do modo do arquivo montado, que varia entre Windows, macOS e Linux.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Usuário sem privilégios. Os comandos privilegiados são executados no host alvo, nunca dentro deste
# container; mantê-lo como root contradiria o princípio de menor privilégio que o trabalho defende.
# O UID 1000 coincide com o primeiro usuário comum em Linux e macOS, o que mantém legível a chave
# SSH montada a partir do host.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin polaris

WORKDIR /app

# Dependências antes do código: mudança em src/ não invalida a camada de instalação.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=polaris:polaris . .

USER polaris

EXPOSE 8000

# Falha rápido se a API subir sem base de conhecimento ou sem banco.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u, sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
