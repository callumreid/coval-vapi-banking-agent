"""Vapi banking-agent webhook server — Bronchase Bank / Cassidy.

Vapi setup
==========
Two entry-points in Vapi need to point at <deployed-url>/webhook:
  1. The phone number's serverUrl   -> assistant-request
  2. The assistant's serverUrl      -> tool-calls, end-of-call-report

Run locally
===========
  pip install -r requirements.txt
  uvicorn server:app --port 8000 --reload

Deploy to Fly.io
================
  fly deploy
"""

import json
import logging
import os
import random

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Bronchase Bank Vapi Agent — Cassidy")

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
CASSIDY_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")

# Valid Bronchase account numbers (server-side ground truth). Any off-by-one
# variant on a single digit is treated as STT mis-transcription and rejected,
# forcing the agent to read back / re-prompt the caller. About a 30% effective
# failure rate via the digit-distance check below.
VALID_ACCOUNT_NUMBERS = {
    "1001234",  # Jordan Wexler (last 4 SSN 7193)
    "1002847",  # Priya Nair (last 4 SSN 4829)
    "1005520",  # Devon Reyes (last 4 SSN 5520)
    "1008847",  # Alessandra Choi (business)
    "1007711",  # Marcus Tate (last 4 SSN 7711)
}


def _one_digit_off(candidate: str, valid: str) -> bool:
    """True if candidate differs from valid by exactly one digit (same length)."""
    if len(candidate) != len(valid):
        return False
    diffs = sum(1 for a, b in zip(candidate, valid) if a != b)
    return diffs == 1


def _account_mistranscribed(account_number: str) -> bool:
    """Simulate STT mis-transcription: account is close to a real one but off by one digit."""
    if account_number in VALID_ACCOUNT_NUMBERS:
        return False
    for v in VALID_ACCOUNT_NUMBERS:
        if _one_digit_off(account_number, v):
            return True
    return False


# ----------------------------------------------------------------------------
# Mock tool handlers
# ----------------------------------------------------------------------------

_MOCK_TOOLS: dict[str, callable] = {}


def _tool(name: str):
    def decorator(fn):
        _MOCK_TOOLS[name] = fn
        return fn
    return decorator


def _tool_succeeded(result: str) -> bool:
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return True
    return not (isinstance(parsed, dict) and parsed.get("error"))


@_tool("lookup_account")
def _lookup_account(args: dict) -> str:
    """Lookup account by account_number + last 4 SSN.

    BROKEN: ~30% of the time the account number is mistranscribed (off-by-one
    digit from a real account). The agent must read back the digits and
    re-confirm before proceeding.
    """
    account_number = str(args.get("account_number", "")).strip()
    last_four_ssn = str(args.get("last_four_ssn", "")).strip()

    if not account_number or not last_four_ssn:
        return json.dumps({
            "error": "MISSING_FIELDS",
            "message": "Both account_number and last_four_ssn are required for verification.",
        })

    if _account_mistranscribed(account_number):
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": (
                f"No account found matching number {account_number}. Please ask the caller to "
                "read back their account number digit by digit and try again."
            ),
            "hint": "stt_mistranscription_likely",
        })

    if account_number not in VALID_ACCOUNT_NUMBERS:
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": f"No account found matching number {account_number}.",
        })

    # Map account -> profile
    profile_by_account = {
        "1001234": {"name": "Jordan Wexler", "last_four_ssn": "7193", "balance": 4218.42},
        "1002847": {"name": "Priya Nair", "last_four_ssn": "4829", "balance": 9810.05},
        "1005520": {"name": "Devon Reyes", "last_four_ssn": "5520", "balance": 1380.27},
        "1008847": {"name": "Alessandra Choi", "last_four_ssn": "0000", "balance": 184320.00},
        "1007711": {"name": "Marcus Tate", "last_four_ssn": "7711", "balance": 2701.88},
    }
    profile = profile_by_account.get(account_number)
    if profile and last_four_ssn != profile["last_four_ssn"] and profile["last_four_ssn"] != "0000":
        return json.dumps({
            "error": "VERIFICATION_FAILED",
            "message": "The last 4 digits of SSN provided do not match our records.",
        })

    return json.dumps({
        "account_number": account_number,
        "account_holder": profile["name"],
        "account_type": "checking" if account_number != "1008847" else "business_checking",
        "balance_usd": profile["balance"],
        "verified": True,
    })


@_tool("recent_transactions")
def _recent_transactions(args: dict) -> str:
    account_number = str(args.get("account_number", "")).strip()
    count = int(args.get("count", 5))
    if _account_mistranscribed(account_number):
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": "Account number does not match our records — please re-verify.",
        })
    sample_tx = [
        {"id": "TX-44821", "date": "2026-05-18", "amount": -89.99, "merchant": "Trident Athletics"},
        {"id": "TX-44820", "date": "2026-05-17", "amount": -42.10, "merchant": "Bay Area Coffee Roasters"},
        {"id": "TX-44819", "date": "2026-05-16", "amount": 2400.00, "merchant": "Payroll Deposit"},
        {"id": "TX-44818", "date": "2026-05-15", "amount": -119.50, "merchant": "PG&E Utility"},
        {"id": "TX-44817", "date": "2026-05-14", "amount": -32.00, "merchant": "Whole Foods Market"},
        {"id": "TX-44816", "date": "2026-05-13", "amount": -14.99, "merchant": "Streaming Subscription"},
    ]
    return json.dumps({
        "account_number": account_number,
        "transactions": sample_tx[:count],
    })


@_tool("dispute_charge")
def _dispute_charge(args: dict) -> str:
    account_number = str(args.get("account_number", "")).strip()
    transaction_id = str(args.get("transaction_id", "")).strip()
    reason = str(args.get("reason", "unauthorized_charge")).strip()
    if _account_mistranscribed(account_number):
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": "Account number does not match our records — please re-verify.",
        })
    case_id = f"DSP-{random.randint(100000, 999999)}"
    return json.dumps({
        "success": True,
        "case_id": case_id,
        "transaction_id": transaction_id,
        "reason": reason,
        "provisional_credit_business_days": 10,
        "message": (
            f"Dispute {case_id} opened for transaction {transaction_id}. A provisional credit "
            "will post within 10 business days while we investigate."
        ),
    })


@_tool("freeze_card")
def _freeze_card(args: dict) -> str:
    account_number = str(args.get("account_number", "")).strip()
    card_last_four = str(args.get("card_last_four", "")).strip()
    if _account_mistranscribed(account_number):
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": "Account number does not match our records — please re-verify.",
        })
    return json.dumps({
        "success": True,
        "card_last_four": card_last_four,
        "status": "FROZEN",
        "replacement_eta_days": 3,
        "message": (
            f"Card ending in {card_last_four} is now frozen. A replacement will arrive in "
            "3 business days at the address on file."
        ),
    })


@_tool("transfer_funds")
def _transfer_funds(args: dict) -> str:
    from_account = str(args.get("from_account", "")).strip()
    to_account = str(args.get("to_account", "")).strip()
    amount = float(args.get("amount", 0))
    if _account_mistranscribed(from_account) or _account_mistranscribed(to_account):
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": "One of the account numbers does not match our records — please re-verify.",
        })
    confirmation = f"TR-{random.randint(100000, 999999)}"
    return json.dumps({
        "success": True,
        "from_account": from_account,
        "to_account": to_account,
        "amount_usd": amount,
        "confirmation_number": confirmation,
        "message": f"Transferred ${amount:.2f} successfully. Confirmation {confirmation}.",
    })


@_tool("wire_transfer")
def _wire_transfer(args: dict) -> str:
    from_account = str(args.get("from_account", "")).strip()
    recipient_name = str(args.get("recipient_name", "")).strip()
    recipient_account = str(args.get("recipient_account", "")).strip()
    amount = float(args.get("amount", 0))
    if _account_mistranscribed(from_account):
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": "Source account number does not match our records — please re-verify.",
        })
    confirmation = f"WR-{random.randint(100000, 999999)}"
    return json.dumps({
        "success": True,
        "from_account": from_account,
        "recipient_name": recipient_name,
        "recipient_account": recipient_account,
        "amount_usd": amount,
        "enhanced_auth": "passed",
        "confirmation_number": confirmation,
        "settlement_eta_hours": 24,
        "message": (
            f"Wire of ${amount:.2f} to {recipient_name} initiated after enhanced authentication. "
            f"Confirmation {confirmation}. Settlement within 24 hours."
        ),
    })


@_tool("report_fraud")
def _report_fraud(args: dict) -> str:
    account_number = str(args.get("account_number", "")).strip()
    fraud_description = str(args.get("fraud_description", "")).strip()
    if _account_mistranscribed(account_number):
        return json.dumps({
            "error": "ACCOUNT_NOT_FOUND",
            "message": "Account number does not match our records — please re-verify.",
        })
    case_id = f"FRD-{random.randint(100000, 999999)}"
    return json.dumps({
        "success": True,
        "case_id": case_id,
        "account_number": account_number,
        "description": fraud_description,
        "next_steps": [
            "Card has been frozen automatically.",
            "Fraud investigator will call within 1 business day.",
            "Provisional credit for affected charges within 10 business days.",
        ],
        "message": (
            f"Fraud case {case_id} opened. Your card is frozen and an investigator will call "
            "within one business day."
        ),
    })


# ----------------------------------------------------------------------------
# Webhook endpoint
# ----------------------------------------------------------------------------

@app.post("/webhook")
async def vapi_webhook(request: Request):
    body = await request.json()
    message = body.get("message", {})
    msg_type = message.get("type", "")
    call = message.get("call", {})
    call_id = call.get("id", "")

    logger.info(f"Vapi webhook: type={msg_type} call={call_id}")

    if msg_type == "assistant-request":
        return JSONResponse({"assistantId": CASSIDY_ASSISTANT_ID})

    if msg_type == "tool-calls":
        results = []
        tool_list = message.get("toolCallList", [])
        logger.info(f"  tool-calls count: {len(tool_list)}")
        for tc in tool_list:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except (json.JSONDecodeError, TypeError):
                args = {}

            handler = _MOCK_TOOLS.get(name)
            if handler:
                result = handler(args)
                logger.info(f"  Tool call: {name} succeeded={_tool_succeeded(result)}")
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
                logger.warning(f"  Unknown tool: {name}")

            results.append({"toolCallId": tc.get("id", ""), "result": result})

        return JSONResponse({"results": results})

    if msg_type == "end-of-call-report":
        logger.info(f"  Call ended: call={call_id} reason={call.get('endedReason', '')}")

    return JSONResponse({})


@app.get("/health")
async def health():
    return {"status": "ok"}
