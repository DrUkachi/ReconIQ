"""Public development ingress limited to signed Slack events and liveness."""
from fastapi import FastAPI

from app.api.slack import events

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_api_route("/slack/events", events, methods=["POST"])


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "reconiq-slack-ingress"}
