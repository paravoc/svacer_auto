FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY svacer_mcp/ svacer_mcp/
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "svacer_mcp.server"]
