import os
import time
import random
from flask import Flask, request, jsonify, g, Response
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)
REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
SYSTEM_PROMPT = "You are a helpful, concise customer support agent for LGND."

# ---- Metrics: declared ONCE at module level, never inside a handler ----

REQUESTS = Counter(
    "agent_requests_total",
    "Total HTTP requests handled by the agent",
    ["endpoint", "method", "status"],
)

LATENCY = Histogram(
    "agent_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

@app.before_request
def start_timer():
    g.start_time = time.perf_counter()

@app.after_request
def record_metrics(response):
    if request.path == "/metrics":
        return response
    # Route TEMPLATE, not the raw path. /order/<id> stays one label value.
    # An unmatched request has no rule at all, so it is bucketed as "unmatched"
    # rather than letting a scanner invent a new series per URL it tries.
    endpoint = request.url_rule.rule if request.url_rule else "unmatched"
    REQUESTS.labels(
        endpoint=endpoint,
        method=request.method,
        status=str(response.status_code),
    ).inc()
    LATENCY.labels(endpoint=endpoint).observe(time.perf_counter() - g.start_time)
    return response

@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

@app.route("/health")
def health():
    return jsonify(status="ok", service="legend-support-agent"), 200

# SYNTHETIC. Exists only so latency and error panels have data on a local
# cluster where /chat cannot run without Bedrock credentials.
@app.route("/work")
def work():
    time.sleep(random.expovariate(1 / 0.15))
    if random.random() < 0.1:
        return jsonify(error="synthetic failure"), 500
    return jsonify(result="done"), 200

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify(error='Send JSON: {"message": "your question"}'), 400
    try:
        client = boto3.client("bedrock-runtime", region_name=REGION)
        resp = client.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": message}]}],
        )
        reply = resp["output"]["message"]["content"][0]["text"]
        return jsonify(reply=reply)
    except (BotoCoreError, ClientError) as e:
        return jsonify(error="Bedrock call failed", detail=str(e)), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
