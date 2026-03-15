# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .

# Installiert Abhängigkeiten nach /root/.local
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Stage 2: Final Image ---
FROM python:3.11-slim AS runner
WORKDIR /code

# Kopiert die installierten Pakete aus der ersten Stage
COPY --from=builder /root/.local /root/.local
# Kopiert deinen Quellcode
COPY ./src .
COPY ./templates ./templates
COPY ./static ./static

# WICHTIG: Den Pfad inklusive /bin hinzufügen, damit flask/pymodbus gefunden werden
ENV PATH=/root/.local/bin:$PATH
# Verhindert, dass Python .pyc Dateien schreibt (spart Platz)
ENV PYTHONDONTWRITEBYTECODE=1
# Sorgt dafür, dass Logs sofort ausgegeben werden
ENV PYTHONUNBUFFERED=1

RUN chmod a+x run.sh
CMD ["./run.sh"]