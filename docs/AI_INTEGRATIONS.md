# ISA AUTO TRADING — Widowmaker, Ollama and Kronos

## Operating design

- **Widowmaker** deterministically frames and optimises model instructions. It treats market context as untrusted data and requires evidence-only JSON decisions.
- **Gemini 3.8 Flash** remains the primary AI decision model and remains subject to the existing free-tier attestation.
- **Ollama** is an optional independent reviewer. If enabled, its response must be valid and agree with Gemini's action; otherwise the engine records HOLD. It never places orders.
- **Kronos** is an optional candle-forecast veto. An opposing forecast blocks a new entry. Set `KRONOS_REQUIRED=true` to block new entries whenever a forecast is unavailable.
- The existing paper broker and server-side risk manager remain the only execution path. Live trading is not implemented.

## Ollama configuration

The trading runner must be able to reach the Ollama API from its host. A local `localhost:11434` URL on your Android phone is not reachable from GitHub-hosted runners. Use a secure, reachable Ollama server or the Ollama cloud API.

GitHub Actions secrets:
- `OLLAMA_API_KEY` — required for Ollama cloud; optional for a private/local endpoint that does not use bearer authentication.

GitHub Actions variables:
- `OLLAMA_ENABLED=true`
- `OLLAMA_BASE_URL=https://ollama.com/api` (or your reachable server's API base URL)
- `OLLAMA_MODEL` — choose a model actually available on your Ollama account/server.
- `OLLAMA_REQUIRED` is not needed: when enabled, Ollama review is mandatory for a non-HOLD decision.

Ollama's chat route is `POST /api/chat`; the client uses `stream:false` and JSON output mode. Local Ollama normally does not require authentication; direct cloud API access requires a bearer API key.

## Kronos configuration

Kronos is published as a Python forecasting model with a `KronosPredictor` interface. It does not provide one universal hosted API URL. This project therefore expects a separately hosted, owner-controlled wrapper endpoint.

GitHub Actions secrets:
- `KRONOS_API_URL` — full HTTPS URL of the wrapper's forecast endpoint.
- `KRONOS_API_KEY` — optional bearer token required by your wrapper.

GitHub Actions variables:
- `KRONOS_ENABLED=true`
- `KRONOS_REQUIRED=true` only after the wrapper is deployed and tested.
- `KRONOS_TIMEOUT_SECONDS=15`

### Required wrapper request

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "1h",
  "pred_len": 3,
  "candles": [
    {
      "timestamp": 1794920000000,
      "open": 90000,
      "high": 90100,
      "low": 89900,
      "close": 90050,
      "volume": 12.5
    }
  ]
}
```

### Required wrapper response

```json
{
  "model": "Kronos-small",
  "forecast": [
    {"open": 90050, "high": 90150, "low": 90000, "close": 90100, "volume": 10},
    {"open": 90100, "high": 90200, "low": 90050, "close": 90140, "volume": 11},
    {"open": 90140, "high": 90200, "low": 90080, "close": 90160, "volume": 9}
  ]
}
```

The wrapper should load `Kronos-small` with `NeoQuasar/Kronos-Tokenizer-base` and `NeoQuasar/Kronos-small`, construct a `KronosPredictor`, and return actual model predictions. Do not return sample or simulated values as live forecasts. Validate symbol/timeframe and candle OHLC integrity server-side. Protect the endpoint with HTTPS and authentication.

## Fail-closed rules

- Ollama disabled: Gemini remains primary as before.
- Ollama enabled but unconfigured, unavailable, malformed or disagreeing: HOLD.
- Kronos disabled: no forecast veto is applied.
- Kronos enabled and unavailable: HOLD when `KRONOS_REQUIRED=true`; otherwise its failure is recorded and the primary signal may continue.
- Kronos forecast opposing Gemini: HOLD.
- No AI provider is allowed to modify risk settings, enable live trading, or bypass the risk manager.
- No API secret is logged or placed in source control.
