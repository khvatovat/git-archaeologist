FROM python:3.11-slim

WORKDIR /app

# Core archaeologist modules (reused as-is)
COPY fetcher.py cleaner.py chunker.py summarizer.py synthesizer.py \
     cache.py exceptions.py renderer.py ./

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/main.py .

CMD ["python", "main.py"]
