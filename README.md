# ISA AUTO TRADING

A dual-market **Forex + crypto paper-trading application**. It includes an optional best-effort scheduled runner on GitHub Actions; it is not a guaranteed 24/7 service.

## Hard operating rules

- **Real capital: $0.** The account begins with **$1,000 virtual paper equity**.
- **Everything must remain free:** public read-only market data, open-source Python dependencies, free-tier AI only, and no paid hosting, subscriptions, API credits or premium endpoints.
- **Paper-only execution.** There is no live broker order route. Deposits, withdrawals and real-money transactions are out of scope.
- If AI is unavailable, free quota is exhausted, market data is unavailable, or an AI response is invalid, new entries are held. There is no rule-based or paid-provider fallback.
- The project must never link a paid billing account or upgrade an API project to a paid tier.

## Markets

- Crypto defaults: BTCUSDT and ETHUSDT using Kraken's free public read-only API.
- Forex defaults: EURUSD and GBPUSD using Yahoo Finance's public chart endpoint. Quotes can be delayed, unavailable or rate-limited.
- USDJPY is intentionally not enabled because the paper ledger is USD-denominated and non-USD quote-currency conversion is not implemented.
- Crypto supports long-only spot paper positions. Forex supports long and unleveraged short paper positions.
- Forex short positions reserve virtual margin; no leverage is used.

## Shared risk limits

- Maximum risk per trade: 1% of current virtual equity.
- Daily loss limit: 3%.
- Maximum peak-to-trough drawdown: 15%.
- Combined Forex + crypto gross exposure: 30% of virtual equity.
- Maximum open positions: 5.
- Position state is persisted in SQLite and restored after restart.

## Gemini 3.8 Flash — free tier only

The model ID is `gemini-3.8-flash`. The official Google API pricing page lists a Free Tier with no token charge for this model, subject to account/model quotas. A paid tier also exists, so:

1. Create a Google AI Studio API key in a project that remains on the Free Tier.
2. Do **not** link Google Cloud billing or enable a paid tier.
3. Set `ISA_GEMINI_API_KEY` as a server-side environment secret.
4. Set `ISA_GEMINI_FREE_TIER_CONFIRMED=true` only after verifying that billing is not linked and the project is still on the Free Tier.

The confirmation flag is an operator attestation, **not** an automated billing-status check. If you cannot guarantee the project is free-tier only, leave it false; the application will not make AI decisions or open new positions. Do not put the key in frontend code, source control, logs or issues. Google states that free-tier content may be used to improve its products; do not send private personal data.

## Zero-cost scheduled runner (public GitHub repository)

The `.github/workflows/isa-paper-cycle.yml` workflow runs one paper cycle every five minutes using standard GitHub-hosted runners. GitHub documents standard runners as free for public repositories. Scheduled workflows are best-effort, can be delayed or skipped, and only run from the repository's default branch. The public-repository schedule can be automatically disabled after 60 days without repository activity.

The workflow stores the small SQLite paper-account database in GitHub Actions cache between runs. Cache storage is not a permanent database service. **If no previous state can be restored, the workflow fails closed instead of silently creating a fresh $1,000 account.** Cache eviction or service changes can stop the agent until state is restored or reviewed. Do not treat this as production-grade persistent storage or guaranteed continuous monitoring.

### One-time setup after the PR is merged

1. Open the repository's **Settings → Secrets and variables → Actions**.
2. Add repository secret `ISA_GEMINI_API_KEY` with your Google AI Studio API key. Never paste the key into chat, a commit, an issue, or frontend code.
3. Add repository secret `ISA_GEMINI_FREE_TIER_CONFIRMED` with the exact value `true` only after checking that the Google AI Studio project remains on the free tier and has no paid billing enabled. Otherwise omit it or set it to `false`; the bot will HOLD.
4. Open **Actions → ISA autonomous paper cycle → Run workflow**.
5. For the first-ever setup only, set `bootstrap` to `true` and run once. This creates the initial $1,000 virtual account and saves its state. Leave `bootstrap` false for all later runs.
6. Check the workflow run summary. Later scheduled runs should restore the saved state and run one cycle. If a run reports missing state, stop and investigate; do not bootstrap again until the previous account state is recovered or you deliberately decide to reset the paper simulation.

The workflow does not install a live broker, use real capital, or call paid services. The AI secret is passed only to the backend process as an environment variable. Removing the secret or setting the free-tier confirmation to false immediately makes AI unavailable and blocks new entries.

## Run locally

Python 3.11+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Keep ISA_GEMINI_FREE_TIER_CONFIRMED=false until free-tier billing status is checked.
python scripts/run_paper.py --cycles 5
```

Run the dashboard separately:

```bash
python dashboard/app.py
```

The dashboard binds to localhost by default. Do not expose it publicly without adding authentication and HTTPS.

## Tests

```bash
pytest -vv
python -m compileall -q src dashboard scripts tests
```

GitHub Actions CI tests are configured for the feature branch and pull requests. The separate scheduled paper runner is activated only after the workflow is merged to the repository's default branch.

## Cost and deployment limits

The Python packages, public read-only market-data endpoints, Gemini Standard Free Tier (within its quotas), and standard GitHub Actions runners for this public repository have $0 listed usage. Provider quotas and terms still apply. The scheduled GitHub runner is best-effort, not guaranteed always-on hosting. No paid infrastructure is provisioned. Do not enable paid billing, paid runner types, subscriptions, or premium endpoints.

## Known limitations

- Yahoo Finance is an unofficial public data source, not an institutional Forex feed; it can be delayed or rate-limited.
- Only USD-quoted FX pairs EURUSD and GBPUSD are enabled. Other quote currencies require conversion support first.
- Crypto is long-only spot paper trading; Forex supports long and unleveraged short simulation.
- Gemini free-tier eligibility and billing attachment cannot be verified from this code; the operator must check Google AI Studio/Cloud billing settings.
- No live trading, real-money performance claim, or guarantee of profitability is provided.
