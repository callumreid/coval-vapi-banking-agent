# Bronchase Bank — Vapi Voice Agent (Cassidy)

Demo banking voice agent for the Coval `coval-banking` org. Hosted on Fly.io, fronts a Vapi assistant with managed LLM/STT/TTS.

## Stack
- Vapi assistant (LLM: `gpt-4o-mini`, STT: Deepgram `nova-2`, TTS: Deepgram `aura-asteria-en`)
- Fly webhook (FastAPI) for tool calls
- 7 mock banking tools, one of which embeds an STT mis-transcription failure mode
- Coval OpenTelemetry trace export for Vapi webhook, banking workflow, tool-call, end-of-call, and Vapi-artifact turn/STT/LLM/TTS spans

## Failure mode
`lookup_account` rejects account numbers that are off-by-one digit from a real account, simulating Deepgram nova-2 mis-transcribing digits. The agent must read back account digits and re-prompt the caller. "Account Read-Back Discipline" and "Identity Verification Enforced" LLM-judge metrics catch failures.

## Coval tracing

This repo is a Vapi/PSTN webhook, so SIP headers are not available for Coval
simulation correlation. The app exposes `POST /register-simulation`, which
accepts `simulation_output_id` or `simulation_id` and matches it to the next
Vapi call with a short TTL. Finished webhook spans are exported to
`https://api.coval.dev/v1/traces` with `X-Simulation-Id`.

Required deployment env:

```bash
COVAL_API_KEY=...
```

Optional deployment env:

```bash
COVAL_TRACE_REGISTRATION_SECRET=...  # defaults to COVAL_API_KEY when unset
COVAL_TRACES_ENDPOINT=https://api.coval.dev/v1/traces
COVAL_CORRELATION_TTL_SECONDS=900
```

Register a simulation before or during a one-call Coval run:

```bash
curl -fsS "$AGENT_BASE_URL/register-simulation" \
  -H "Content-Type: application/json" \
  -H "x-coval-registration-secret: $COVAL_TRACE_REGISTRATION_SECRET" \
  -d '{"simulation_output_id":"<simulation-output-id>","run_id":"<run-id>"}'
```

If `COVAL_TRACE_REGISTRATION_SECRET` is not configured, use `x-api-key:
$COVAL_API_KEY` instead. Do not put either value in code or committed config.
