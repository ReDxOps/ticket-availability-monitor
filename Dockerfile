# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Metadonnées
LABEL maintainer="Dream Nation Monitor Team"
LABEL description="Service de surveillance 24h/24 pour la billetterie See Tickets Resell (Dream Nation 2026)"

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Création d'un utilisateur non-privilégié pour la sécurité
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app appuser

# Installation des dépendances
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copie du code source
COPY src/ src/
COPY scripts/ scripts/

# Création et configuration du dossier de données pour la base SQLite
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

# Bascule vers l'utilisateur non-root
USER appuser

# Healthcheck : vérifie que le runtime Python fonctionne
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import src.config, sys; sys.exit(0)" || exit 1

# Démarrage du moniteur
CMD ["python", "-m", "src.monitor"]
