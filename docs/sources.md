# Sources & review dates

## Fact sources

| Fact | Value | Source URL | Reviewed |
|------|-------|-----------|----------|
| GitHub Copilot usage-based billing | Pro $10 (=$10 credits), Pro+ $39, Business $19/user, Enterprise $39/user | https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/ | 2026-09-04 |
| Copilot billing start date | 2026-06-01 | https://github.blog/news-insights/company-news/github-copilot-is-moving-to-usage-based-billing/ | 2026-09-04 |
| Anthropic subscriptions cost comparison | ≈15–30x cheaper than API-equivalent; 440 sessions / 18,000 turns ≈ $1,588 API-equivalent covered by $200 plan | https://www.productcompass.pm/p/claude-code-pricing | 2026-09-04 |
| Claude API `/usage` breakdown | No per-model/project breakdown available | https://www.productcompass.pm/p/claude-code-pricing | 2026-09-04 |
| Claude Haiku 4.5 pricing | $1 per MTok input / $5 per MTok output | https://www.cloudzero.com/blog/claude-pricing/ | 2026-09-04 |
| Claude Sonnet 5 pricing | $2 per MTok input / $10 per MTok output | https://www.cloudzero.com/blog/claude-pricing/ | 2026-09-04 |
| Claude Opus 5 pricing | $5 per MTok input / $25 per MTok output | https://www.cloudzero.com/blog/claude-pricing/ | 2026-09-04 |
| Claude Fable 5.1 pricing | $10 per MTok input / $50 per MTok output | https://www.cloudzero.com/blog/claude-pricing/ | 2026-09-04 |
| OpenAI GPT-5.6 Luna pricing | $0.20 per MTok input / $1.20 per MTok output | https://www.cloudzero.com/blog/openai-pricing/ | 2026-09-04 |
| OpenAI GPT-5.6 Terra pricing | $2 per MTok input / $12 per MTok output | https://www.cloudzero.com/blog/openai-pricing/ | 2026-09-04 |
| OpenAI GPT-5.6 Sol pricing | $5 per MTok input / $30 per MTok output | https://www.cloudzero.com/blog/openai-pricing/ | 2026-09-04 |
| gpt-oss-120b via OpenRouter pricing | $0.03 per MTok input / $0.17 per MTok output | https://openrouter.ai/openai/gpt-oss-120b | 2026-09-04 |
| German household electricity rate | 37.0 ct/kWh | https://www.rechnerportal.net/news/bdew-haushaltsstrompreis-2026/ | 2026-09-04 |
| German PV feed-in tariff (≤10 kWp) | 7.71 ct/kWh (Aug 2026–Jan 2027) | https://photovoltaik.org/kosten/einspeiseverguetung | 2026-09-04 |
| Residential PV LCOE | 6.3–14.4 ct/kWh, small rooftop systems ≤30 kWp (mid-range used: 10.4 ct/kWh) | "Levelized Cost of Electricity – Renewable Energy Technologies", Fraunhofer ISE, July 2024: https://www.ise.fraunhofer.de/content/dam/ise/en/documents/publications/studies/EN2024_ISE_Study_Levelized_Cost_of_Electricity_Renewable_Energy_Technologies.pdf | 2026-09-12 |
| Gemini CLI free quota | 1000 req/day | https://google-gemini.github.io/gemini-cli/docs/quota-and-pricing.html | 2026-09-04 |
| Gemini CLI Standard quota | 1500 req/day | https://google-gemini.github.io/gemini-cli/docs/quota-and-pricing.html | 2026-09-04 |
| Gemini CLI Enterprise quota | 2000 req/day | https://google-gemini.github.io/gemini-cli/docs/quota-and-pricing.html | 2026-09-04 |
| Codex rollout schema | token_count + rate_limits | https://github.com/openai/codex | 2026-09-04 |
| Gemini CLI chat recording schema | chatRecordingService implementation | https://github.com/google-gemini/gemini-cli | 2026-09-04 |
| Hermes state.db schema | Session storage implementation | https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage/ | 2026-09-04 |
| OpenRouter key/limits API | Rate limiting API reference | https://openrouter.ai/docs/api-reference/limits | 2026-09-04 |
| Llama-GENBA-10B | Trilingual DE/EN/Bavarian, 164B training tokens (LRZ + Cerebras) | https://www.lrz.de/en/news/detail/lrz-develops-10b-language-model | 2026-09-04 |
| llama.cpp Apple Silicon performance | Benchmark data available | https://github.com/ggml-org/llama.cpp/discussions/4167 | 2026-09-04 |

## Reverse-engineered endpoints (may break without notice)

- **Copilot**: `GET api.github.com/copilot_internal/user`
- **Anthropic**: `GET api.anthropic.com/api/oauth/usage` (header: `anthropic-beta: oauth-2025-04-20`, heavily rate limited)
- **Gemini**: `POST cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`
- **Codex**: `GET chatgpt.com/backend-api/codex/usage`

**Note**: token-finops does not call any of these endpoints by default.
