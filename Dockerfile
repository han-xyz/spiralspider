FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    SPIRALTOOLS=/opt/spiraltools

RUN pip install --no-cache-dir "playwright==1.47.0" \
    && playwright install --with-deps chromium

# The spiraltools package of spiraldb, from the build context named "spiraltools" (spiraldb/tools).
COPY --from=spiraltools spiraltools /opt/spiraltools/spiraltools

WORKDIR /app
COPY pyproject.toml README.md ./
COPY spiralspider ./spiralspider
RUN pip install --no-cache-dir --no-deps .

RUN useradd --create-home --uid 1000 spider && mkdir -p /work/out /work/cache && chown spider /work/out /work/cache
USER spider
WORKDIR /work
ENTRYPOINT ["spiralspider"]
