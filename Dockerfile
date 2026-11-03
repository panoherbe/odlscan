FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY odlscan ./odlscan
# NumPy und Matplotlib wie im gemessenen Lauf (nachweis/), damit ein Neubau dieselben Zahlen liefert
RUN pip install --no-cache-dir "numpy==2.5.4" "matplotlib==3.11.2" ".[plots,test]"
COPY tests ./tests
ENTRYPOINT ["odlscan"]
CMD ["--help"]
