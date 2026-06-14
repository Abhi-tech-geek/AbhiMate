# AbhiMate — production container (Railway / Render / Fly.io)
#
# Ships Chromium + its matching driver as system packages so the Selenium
# executor runs without any runtime download. App binds to $PORT (set by the
# host) and runs headless by default.

FROM python:3.11-slim

# --- System deps: Chromium + driver + fonts -------------------------------
# chromium-driver from Debian is always version-matched to chromium, so we
# never hit the "driver/browser version mismatch" class of errors.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Tell AbhiMate where the system Chromium + driver live (read in
# utils/automation_drivers.py).
ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# --- Runtime config: headless + bind to all interfaces --------------------
# These default the app for a server; override any of them in the host's
# dashboard if needed.
ENV ABHIMATE_HEADLESS=true \
    ABHIMATE_HOST=0.0.0.0 \
    ABHIMATE_DEBUG=false \
    ABHIMATE_BACKEND=selenium

WORKDIR /app

# Install Python deps first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source.
COPY . .

# Create the runtime data dirs the app writes to (gitignored, so not in the
# build context as real files — just the .keep placeholders may exist).
RUN mkdir -p data/screenshots data/traces data/junit data/auth_states \
             data/baselines data/sessions database

# Railway/Render/Fly inject $PORT. Default to 5000 for local `docker run`.
ENV PORT=5000
EXPOSE 5000

# Start via the app's own __main__ (boots the scheduler + threaded SSE).
# We read $PORT into ABHIMATE_PORT at container start so the host's assigned
# port is honoured.
CMD ["sh", "-c", "ABHIMATE_PORT=${PORT:-5000} python app.py"]
