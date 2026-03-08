FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY static/ static/

RUN pip install --no-cache-dir -e .

EXPOSE 8080

CMD ["uvicorn", "ev_route_agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
