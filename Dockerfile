FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY odlscan ./odlscan
RUN pip install --no-cache-dir ".[plots,test]"
COPY tests ./tests
ENTRYPOINT ["odlscan"]
CMD ["--help"]
