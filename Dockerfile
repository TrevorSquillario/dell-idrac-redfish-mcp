FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build deps for possible compiled packages
RUN apt-get update \
	&& apt-get install -y --no-install-recommends build-essential gcc libffi-dev \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/ /app/

# Run as non-root user
RUN addgroup --system app && adduser --system --ingroup app app \
	&& chown -R app:app /app
USER app

EXPOSE 8080

CMD ["python", "fastmcp_server.py"]

