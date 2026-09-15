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
| Cloud LLM inference energy | **ESTIMATE** ~600 Wh per 1M output tokens (accelerator-side): Epoch AI's ~0.3 Wh/query for GPT-4o divided by the 500 output tokens/query Epoch itself assumes. No provider publishes energy per token. Jegham et al. (arXiv:2505.09598) implies ~1410 Wh/1M (2.4x); Luccioni et al. (FAccT '24) implies ~4700 Wh/1M at 10 tokens/inference. Defensible range 600–1500; the low end is used. | https://epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use | 2026-09-15 |
| Cloud LLM inference energy (production-measured, unusable per-token) | 0.24 Wh, 0.03 gCO2e, 0.26 mL water per median Gemini Apps text prompt (May 2025). The only in-production measurement, but the paper discloses no token counts, so it cannot be converted per-token. | https://arxiv.org/abs/2508.15734 | 2026-09-15 |
| Hyperscale datacentre PUE | 1.13 — midpoint of Google 1.09 (CY2025 TTM), AWS 1.14 (CY2025 global), Microsoft 1.17 (FY25). The commonly-quoted Microsoft 1.18 is their stale 2022 first disclosure. Industry-wide average is 1.52 (Uptime Institute 2026), but hyperscale AI serving does not run in an average facility. | https://datacenters.google/efficiency/ , https://sustainability.aboutamazon.com/products-services/aws-cloud , https://datacenters.microsoft.com/sustainability/efficiency/ | 2026-09-15 |
| US national-average grid carbon intensity | 350 gCO2e/kWh — EPA eGRID2023 rev2 (pub. 12 Jun 2025, data year 2023), 770.884 lb/MWh = 349.7 g/kWh. EIA data year 2024 gives 785 lb/MWh = 356 g/kWh. eGRID2024 not released as of Sep 2026. | https://www.epa.gov/system/files/documents/2025-06/summary_tables_rev2.pdf | 2026-09-15 |
| Northern Virginia grid carbon intensity ("Data Center Alley") | 270 gCO2e/kWh — EPA eGRID2023 subregion SRVC; EIA Virginia state profile (2024) gives 286. ~20–30% **cleaner** than the US average (~28–40% nuclear, ~1.9% coal). CAVEAT: Virginia imports ~30% of consumed power from the dirtier western PJM pool (RFCW ~416 g/kWh), so a consumption-based figure would be higher. | https://www.eia.gov/electricity/state/virginia/ | 2026-09-15 |
| Texas / ERCOT grid carbon intensity | 334 gCO2e/kWh — EPA eGRID2023 subregion ERCT; EIA Texas state profile (2024) gives 373. Gas ~50% of generation but wind+solar ~28.5%, so a "gas-heavy" grid still lands at/below the national average. | https://www.eia.gov/electricity/state/texas/ | 2026-09-15 |
| German grid carbon intensity | 344 gCO2/kWh for 2025 (estimate vintage), direct-combustion convention. Series: 2023 final 379, 2024 preliminary 353, 2025 estimate 344 — preliminary vintages get revised by up to ~10 g. Lifecycle equivalent 406 gCO2eq/kWh. Supersedes the previous 380, which was the 2023 figure in its first published vintage. | Umweltbundesamt CC 16/2026 (pub. Mar 2026): https://www.umweltbundesamt.de/system/files/medien/11850/publikationen/2026-03/16_2026_CC.pdf | 2026-09-15 |
| MacBook Pro 16" M4 Max 48 GB | **APPROXIMATE** $3,699 US list (48 GB/1 TB build); 140 W adapter; 75 W estimated sustained system draw under LLM decode; 22 tok/s on Qwen3 32B Q4 (estimate, laptop throttling vs. Mac Studio M4 Max) | Apple pricing page; power and tok/s are estimates — see `savings/hardware_profiles.json` `_laptop_note` | 2026-09-15 |
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
