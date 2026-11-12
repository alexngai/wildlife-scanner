# One image for the API and the scheduled worker (docs/deploy.md).
# Build from the repository root: docker build -f deploy/Dockerfile -t wildlife-radar .
FROM python:3.13-slim

RUN pip install --no-cache-dir uv==0.11.32

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --extra deploy --no-install-project

# The region packs and profiles are read from the source tree, so the project is installed
# editable (uv's default) next to them.
COPY src src
COPY regions regions
COPY profiles profiles
RUN uv sync --locked --no-dev --extra deploy

ENV PATH=/app/.venv/bin:$PATH
RUN useradd --create-home --uid 1000 app
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
# Starts as root only to fix the volume's owner; the command runs as "app".
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

EXPOSE 8080
CMD ["wildlife-radar", "serve", "--host", "0.0.0.0", "--port", "8080", "--cache-dir", "/tmp/bundles"]
