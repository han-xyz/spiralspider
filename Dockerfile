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
# Scrapy and scrapy-playwright at releases that resolve with the image's Playwright 1.47, which stays as it is.
RUN pip install --no-cache-dir . scrapy==2.19.0 scrapy-playwright==0.0.48 playwright==1.47.0

RUN useradd --create-home --uid 1001 spider && mkdir -p /work/out /work/cache && chown -R spider /work /ms-playwright
USER spider
WORKDIR /work
ENTRYPOINT ["spiralspider"]
