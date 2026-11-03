# API image. Stage 1 builds the demo database through the real daily pipeline (needs dbt);
# stage 2 is the small runtime that only serves it.
FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY dbt ./dbt
COPY benchmarks ./benchmarks
RUN pip install --no-cache-dir -e ".[dev]"
RUN mkdir -p data/ui \
 && python -m tally generate --seed 42 --days 60 --out data/ui/world \
 && python -m tally split --world data/ui/world --out data/ui/batches --late-rate 0.05 --seed 1 \
 && python -m tally backfill --db data/ui/serve.duckdb --batches data/ui/batches --start 2026-01-01 --end 2026-03-04 \
 && python -c "import duckdb; c=duckdb.connect('data/ui/serve.duckdb'); c.execute('CHECKPOINT')" \
 && rm -rf data/ui/world data/ui/batches

FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home tally
COPY pyproject.toml README.md ./
COPY src ./src
COPY benchmarks ./benchmarks
RUN pip install --no-cache-dir -e ".[api]"
COPY --from=build /app/data/ui/serve.duckdb /app/data/serve.duckdb
RUN chown -R tally /app
USER tally
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "tally", "serve", "--db", "/app/data/serve.duckdb", "--host", "0.0.0.0", "--port", "8000"]
