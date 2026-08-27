FROM ghcr.io/ggml-org/llama.cpp:server-b10524 AS llama-server

FROM ubuntu:24.04

LABEL org.opencontainers.image.title="Archive Workbench" \
      org.opencontainers.image.description="Aplicación local para investigación archivística - CPU" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/alexdcolman/archive-workbench" \
      org.opencontainers.image.variant="cpu"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=1024 \
    PATH="/opt/archive-workbench/.venv/bin:${PATH}" \
    LLAMA_CPP_BINARY=/opt/llama/llama-server \
    SURYA_INFERENCE_BACKEND=llamacpp \
    ARCHIVE_WORKBENCH_SURYA_BACKEND=llamacpp

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      ffmpeg \
      libgl1 \
      libglib2.0-0 \
      libgomp1 \
      libmagic1 \
      libvips42 \
      python3 \
      python3-pip \
      python3-venv \
      tesseract-ocr \
      tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

COPY --from=llama-server /app /opt/llama
ENV LD_LIBRARY_PATH="/opt/llama"
RUN test -f /opt/llama/libllama-server-impl.so \
    && /opt/llama/llama-server --version

WORKDIR /opt/archive-workbench

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src

RUN python3 -m venv /opt/archive-workbench/.venv \
    && python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install ".[extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]" \
    && python -m pip check

# Surya queda aislado del runtime principal. La imagen CPU instala PyTorch
# desde el índice CPU y usa el llama-server CPU incluido en esta imagen.
RUN python3 -m venv /opt/archive-workbench/.venv-surya \
    && /opt/archive-workbench/.venv-surya/bin/python -m pip install --upgrade pip \
    && /opt/archive-workbench/.venv-surya/bin/python -m pip install \
         --index-url https://download.pytorch.org/whl/cpu \
         "torch>=2.7.0,<3" "torchvision>=0.20.0,<1" \
    && /opt/archive-workbench/.venv-surya/bin/python -m pip install "surya-ocr==0.22.1" \
    && /opt/archive-workbench/.venv-surya/bin/python -m pip check \
    && /opt/archive-workbench/.venv-surya/bin/python -c \
         "import torch; assert torch.version.cuda is None; print('surya_torch=cpu')"

COPY docker/container-entrypoint.sh /usr/local/bin/archive-workbench-container
RUN chmod 0755 /usr/local/bin/archive-workbench-container

EXPOSE 8501

HEALTHCHECK --interval=5s --timeout=3s --start-period=30s --retries=24 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2).read()" || exit 1

ENTRYPOINT ["/usr/local/bin/archive-workbench-container"]
