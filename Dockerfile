FROM --platform=linux/amd64 python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app

# Build wheelhouse and install packages into a relocatable dir matching final Python (3.11)
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python -m pip wheel --no-cache-dir -w /wheels . \
 && python -m pip install --no-cache-dir --no-index --find-links=/wheels -t /opt/site-packages backend

# Download Freerouting JAR without curl (use Python stdlib)
RUN python -c "import os,urllib.request; os.makedirs('/opt/freerouting',exist_ok=True); urllib.request.urlretrieve('https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar','/opt/freerouting/freerouting.jar'); print('Downloaded freerouting.jar')"

FROM --platform=linux/amd64 ghcr.io/kicad/kicad:9.0.4

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LC_ALL=C.UTF-8 LANG=C.UTF-8 \
    KICAD_PY=python3 \
    FREEROUTING_JAR=/opt/freerouting/freerouting.jar \
    PORT=8080

USER root

# Ensure KiCad in base image is 9.x (fail build otherwise)
RUN python3 -c "import sys,re; import pcbnew; v=str(pcbnew.GetBuildVersion()); print('KiCad version:',v); sys.exit(0 if re.match(r'^9\\.', v) else 1)"

WORKDIR /app
COPY . /app
COPY --from=builder /opt/site-packages /opt/site-packages
RUN ln -sf /usr/bin/python3 /opt/venv/bin/python || true
COPY --from=builder /opt/freerouting /opt/freerouting

ENV PYTHONPATH=/opt/site-packages:$PYTHONPATH

EXPOSE 8080

# Run uvicorn via system python with injected site-packages (no pip in final)
CMD ["bash","-lc","python3 -m uvicorn app.src.main:app --host 0.0.0.0 --port ${PORT}"]

USER root
# Install xvfb and Java 21 (Adoptium Temurin JRE) via APT (Debian bookworm)
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg \
    && chmod a+r /etc/apt/keyrings/adoptium.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb bookworm main" > /etc/apt/sources.list.d/adoptium.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends temurin-21-jre \
    && rm -rf /var/lib/apt/lists/* \
    && update-ca-certificates \
    && java -version

ENV JAVA_HOME=/usr/lib/jvm/temurin-21-jre-amd64
ENV PATH=${JAVA_HOME}/bin:${PATH}
