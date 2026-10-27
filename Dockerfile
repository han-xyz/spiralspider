# Microsoft's Playwright image ships Chromium and its system dependencies for this Playwright version.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SPIRALTOOLS=/opt/spiraltools

# The spiraltools package of spiraldb, from the build context named "spiraltools" (spiraldb/tools).
COPY --from=spiraltools spiraltools /opt/spiraltools/spiraltools

WORKDIR /app
COPY pyproject.toml README.md ./
COPY spiralspider ./spiralspider
RUN pip install --no-cache-dir --no-deps .

RUN useradd --create-home --uid 1001 spider && mkdir -p /work/out /work/cache && chown -R spider /work /ms-playwright
USER spider
WORKDIR /work
ENTRYPOINT ["spiralspider"]
