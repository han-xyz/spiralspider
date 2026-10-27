# Microsoft's Playwright image ships Chromium and its system dependencies for this Playwright version.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/

# The image's system Python (3.10 on jammy) runs the project's environment; its browsers stay where the image put them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPIRALTOOLS=/opt/spiraltools \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/bin/python3 \
    UV_PYTHON_DOWNLOADS=never

# The spiraltools package of spiraldb, from the build context named "spiraltools" (spiraldb/tools).
COPY --from=spiraltools spiraltools /opt/spiraltools/spiraltools

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY spiralspider ./spiralspider
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1001 spider && mkdir -p /work/out /work/cache && chown -R spider /work /ms-playwright
USER spider
WORKDIR /work
ENTRYPOINT ["/opt/venv/bin/spiralspider"]
