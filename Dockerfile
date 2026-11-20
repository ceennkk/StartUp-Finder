FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY startup_finder ./startup_finder
RUN pip install --no-cache-dir '.[live]'
ENV HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "-m", "startup_finder", "serve"]
