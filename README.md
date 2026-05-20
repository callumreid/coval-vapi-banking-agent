# Bronchase Bank — Vapi Voice Agent (Cassidy)

Demo banking voice agent for the Coval `coval-banking` org. Hosted on Fly.io, fronts a Vapi assistant with managed LLM/STT/TTS.

## Stack
- Vapi assistant (LLM: `gpt-4o-mini`, STT: Deepgram `nova-2`, TTS: Deepgram `aura-asteria-en`)
- Fly webhook (FastAPI) for tool calls
- 7 mock banking tools, one of which embeds an STT mis-transcription failure mode

## Failure mode
`lookup_account` rejects account numbers that are off-by-one digit from a real account, simulating Deepgram nova-2 mis-transcribing digits. The agent must read back account digits and re-prompt the caller. "Account Read-Back Discipline" and "Identity Verification Enforced" LLM-judge metrics catch failures.
