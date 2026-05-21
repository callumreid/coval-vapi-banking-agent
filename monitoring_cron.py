"""Monitoring cron — picks a random transcript from pool/transcripts.json and
posts it to Coval's `/v1/conversations:submit` so it lands as a MONITORING
conversation with default metrics applied.

Fly cron invocation
===================
  fly machines run --schedule=hourly \
      -e COVAL_API_KEY=$COVAL_API_KEY \
      -e COVAL_AGENT_ID=$COVAL_AGENT_ID \
      callumcoval/coval-vapi-banking-agent:latest \
      python monitoring_cron.py
"""

import json
import logging
import os
import random
import sys
from datetime import datetime, timezone

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

COVAL_BASE_URL = os.environ.get("COVAL_BASE_URL", "https://api.coval.dev")
COVAL_API_KEY = os.environ.get("COVAL_API_KEY", "")
COVAL_AGENT_ID = os.environ.get("COVAL_AGENT_ID", "")
POOL_PATH = os.environ.get("POOL_PATH", "/app/pool/transcripts.json")

# Bronchase Bank monitoring metric panel — fires on every cron-submitted
# conversation. Mirrors the "default_monitoring_metrics" pattern used by
# orgs like Yelp/Upstart, applied per-submit because the org-level field
# is admin-only.
#
#   mcQXZCsaqh2zBJPR7Thdvv  Conversation Success           (catch-all)
#   kbrdk2BpHZqpfYU7nXxi7P  Account Read-Back Discipline   (catches STT mis-transcription)
#   AC2rTByy8Hbn6MsaBZKHq5  Identity Verification Enforced (regulatory)
#   C3Stso3JxATCxFHyzA3kxS  Scam Detection                 (adversarial)
#   ntXD4Qp3ni4pJtMWFtRkbz  Workflow Completion Rate       (trace metric)
DEFAULT_MONITORING_METRICS = [
    "mcQXZCsaqh2zBJPR7Thdvv",
    "kbrdk2BpHZqpfYU7nXxi7P",
    "AC2rTByy8Hbn6MsaBZKHq5",
    "C3Stso3JxATCxFHyzA3kxS",
    "ntXD4Qp3ni4pJtMWFtRkbz",
]


def main() -> int:
    if not COVAL_API_KEY:
        logger.error("COVAL_API_KEY env var not set; aborting.")
        return 1
    if not COVAL_AGENT_ID:
        logger.error("COVAL_AGENT_ID env var not set; aborting.")
        return 1

    try:
        with open(POOL_PATH, "r") as f:
            pool = json.load(f)
    except FileNotFoundError:
        logger.error(f"Pool file not found at {POOL_PATH}; aborting.")
        return 1
    except json.JSONDecodeError as e:
        logger.error(f"Pool file corrupted: {e}; aborting.")
        return 1

    if not pool:
        logger.warning(f"Pool at {POOL_PATH} is empty; nothing to submit.")
        return 0

    entry = random.choice(pool)
    transcript = entry.get("transcript") if isinstance(entry, dict) else entry

    payload = {
        "agent_id": COVAL_AGENT_ID,
        "transcript": transcript,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "metrics": DEFAULT_MONITORING_METRICS,
        "metadata": {
            "source": "fly_cron_monitoring",
            "vertical": "banking",
            "brand": "Bronchase Bank",
            "environment": "production",
        },
    }

    url = f"{COVAL_BASE_URL}/v1/conversations:submit"
    headers = {"x-api-key": COVAL_API_KEY, "Content-Type": "application/json"}

    logger.info(f"POST {url} (transcript length={len(transcript) if transcript else 0})")
    resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
    logger.info(f"  status={resp.status_code} body={resp.text[:300]}")
    return 0 if resp.status_code < 400 else 2


if __name__ == "__main__":
    sys.exit(main())
