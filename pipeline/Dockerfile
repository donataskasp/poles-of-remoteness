# GDAL 3.13.3 on Ubuntu 26.04 (python3.14, osmium-tool 1.19 from universe).
# Check https://github.com/OSGeo/gdal/pkgs/container/gdal for the tag.
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.13.3

ARG PMTILES_VERSION=1.31.2
RUN apt-get update \
 && apt-get install -y --no-install-recommends osmium-tool python3-venv python3-pip curl ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && arch="$(uname -m)" && case "$arch" in x86_64) pm=x86_64 ;; aarch64) pm=arm64 ;; *) echo "unsupported arch $arch" && exit 1 ;; esac \
 && curl -fsSL "https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION}_Linux_${pm}.tar.gz" \
    | tar -xz -C /usr/local/bin pmtiles \
 && pmtiles version

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps -e /app
ENV PATH="/opt/venv/bin:${PATH}" POLES_WORK=/work POLES_REGIONS=/app/regions
VOLUME ["/work"]
ENTRYPOINT ["poles"]
CMD ["--help"]
