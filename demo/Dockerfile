FROM python:3.11-slim

WORKDIR /app

# Install build dependencies and pip
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# When the build `context` is `./demo`, the files are at the root of the context.
# Copy the contents of the build context into the image's workdir.
COPY ./src/ /app/

EXPOSE 7860

CMD ["python", "chat.py"]
