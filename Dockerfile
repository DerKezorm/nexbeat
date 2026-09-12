# nexbeat als ein einziger Container.
#
# Zwei Stufen: erst wird die Oberflaeche gebaut, dann landen nur die fertigen
# Dateien im Abbild. Node und node_modules bleiben draussen, im Betrieb liefert
# FastAPI die gebauten Dateien mit aus.

# --- Stufe 1: Oberflaeche bauen ---------------------------------------------
#
# --platform=$BUILDPLATFORM: Das Abbild entsteht fuer amd64 und arm64. Ohne die
# Angabe liefe auch diese Stufe unter Emulation, und "npm ci" unter emuliertem
# ARM ist sehr langsam. Aus dieser Stufe wandert nur /build/dist weiter, also
# HTML, CSS und JavaScript ohne Architekturbezug.
FROM --platform=$BUILDPLATFORM node:22-alpine AS oberflaeche

WORKDIR /build

# Erst nur die Abhaengigkeiten: Solange sie gleich bleiben, nimmt Docker beim
# naechsten Bau den Zwischenstand und spart "npm ci".
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- Stufe 2: Laufzeit -------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXBEAT_DATA_DIR=/data \
    NEXBEAT_FRONTEND_DIST=/app/static

WORKDIR /app

# curl fuer den Healthcheck, gosu zum Ablegen der Administratorrechte beim Start.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gosu \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=oberflaeche /build/dist ./static

# Der Benutzer, unter dem nexbeat laeuft. Der Container startet als
# Administrator und gibt die Rechte im Startskript ab, siehe dort.
RUN useradd --system --create-home --uid 1000 nexbeat \
    && mkdir -p /data \
    && chown -R nexbeat:nexbeat /data /app

COPY docker/entrypoint.sh /entrypoint.sh
# Entfernt Windows-Zeilenenden: Unter Windows ausgecheckt, startete das Skript sonst nicht.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

VOLUME ["/data"]
# Nur eine Angabe fuer Werkzeuge. Der tatsaechliche Port kommt aus NEXBEAT_PORT.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${NEXBEAT_PORT:-8000}/api/health" || exit 1

# ⚠️ Ein Arbeitsprozess: SQLite, und der Abgleich mit Lidarr darf nur einmal laufen.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--workers", "1"]
