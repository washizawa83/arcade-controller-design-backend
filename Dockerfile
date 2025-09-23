FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LC_ALL=C.UTF-8 LANG=C.UTF-8

# System deps: Python 3.12, KiCad 9 (pcbnew Python API), OpenJDK (Freerouting), Xvfb for headless wx
RUN set -e; \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      curl ca-certificates gnupg git software-properties-common \
      openjdk-21-jdk-headless \
      xvfb fonts-dejavu && \
    add-apt-repository -y ppa:kicad/kicad-9.0-releases && \
    apt-get update && \
    apt-get install -y --no-install-recommends kicad && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Create a virtualenv that can see system site-packages (for pcbnew)
RUN python3 -m venv /opt/venv --system-site-packages \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install --no-cache-dir .

# Freerouting JAR (pin version and validate)
# Try a set of known URLs for Freerouting jar (latest and pinned), validate with jar
RUN set -e; mkdir -p /opt/freerouting; \
    # Known good commit artifact (replace with a verified mirror if needed)
    URL_1="https://github.com/freerouting/freerouting/releases/download/v2.1.0/freerouting-2.1.0.jar"; \
    echo "Downloading $URL_1"; \
    curl -fL -o /opt/freerouting/freerouting.jar "$URL_1"; \
    # Validate jar
    if ! (jar tf /opt/freerouting/freerouting.jar >/dev/null 2>&1); then \
      echo "Freerouting jar validation failed" >&2; exit 1; \
    fi

# Runtime env
ENV PATH=/opt/venv/bin:$PATH \
    KICAD_PY=python3 \
    FREEROUTING_JAR=/opt/freerouting/freerouting.jar \
    PORT=8080

EXPOSE 8080

# Some KiCad APIs require wx initialisation; xvfb-run helps headless execution
CMD ["bash","-lc","xvfb-run -a uvicorn app.src.main:app --host 0.0.0.0 --port ${PORT}"]


