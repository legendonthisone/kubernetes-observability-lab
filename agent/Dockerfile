FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /venv
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
RUN useradd --create-home --uid 1001 appuser
COPY --from=builder /venv /venv
WORKDIR /app
COPY . .
USER appuser
EXPOSE 5000
CMD ["/venv/bin/python", "app.py"]
