FROM python:3.12-slim

# Don't run as root inside the container.
RUN useradd --create-home app
WORKDIR /app

# Install dependencies first so Docker can cache this layer between builds.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# The dataset is read from /app/data at runtime.
COPY data ./data

USER app

# Listen on all interfaces so the platform's router can reach the server.
# Railway sets $PORT; the server reads it automatically.
CMD ["python", "-m", "job_postings_mcp", "--http", "--host", "0.0.0.0"]
