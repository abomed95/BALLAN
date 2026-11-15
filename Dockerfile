# Image unique du service BALLAN : API, rappels, migrations et import.
# La commande choisit le role : servir (defaut), rappels, migrer, importer...
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependances d'abord : la couche reste en cache tant que le verrou ne change pas.
COPY requirements/serveur.lock requirements/serveur.lock
RUN pip install -r requirements/serveur.lock

COPY core core
COPY verticals verticals
COPY application application
COPY migrations migrations
COPY exemples exemples

RUN useradd --system --uid 10001 --no-create-home ballan
USER ballan

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante', timeout=3)" || exit 1

ENTRYPOINT ["python", "-m", "application"]
CMD ["servir", "--hote", "0.0.0.0", "--port", "8000"]
