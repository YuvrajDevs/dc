# Card-network layer

The reconciliation world records what the merchant's books, the processor and the bank say. This layer adds what happened on the card network for every one of those payments, so the same warehouse can answer approval, dispute and fee questions. It lives in `src/trueup/synth/network.py` and draws from its own random streams, so the reconciliation tables (and their frozen benchmark floors) are byte-identical with or without it.

## Sources
| File | One row per | Notes |
|---|---|---|
| `merchant_profiles` | merchant | MCC (ISO 18245), category group, country, region, share of online sales |
| `card_bins` | BIN | network, product (debit, credit, premium, commercial), issuer, issuer region |
| `authorizations` | attempt | ISO 8583-style response code, entry mode, 3-D Secure, `retry_of` for soft-decline retries; every captured payment has exactly one approved authorization, joined on `order_ref` |
| `clearing_records` | captured payment | interchange rate and amount, scheme fee, `standard` or `downgraded` qualification |
| `refunds` | refund | full or partial, 1 to 20 days after capture |
| `disputes` | dispute | category, Visa or Mastercard reason code, response deadline, response date, outcome |
| `interchange_schedule` | product × channel | the published rate card the analytics audit against |

Each source has a schema contract (types, allowed values, cross-field rules such as "approved must agree with response code 00"). Daily deliveries split them by event date, so disputes keep arriving weeks after the sales window, as they do in practice.

## Marts
| Model | Answers |
|---|---|
| `fct_authorization` | every attempt with issuer, product, channel, cross-border flag, soft or hard decline, recovered by retry |
| `fct_clearing` | interchange charged vs the rate card rebuilt in SQL; `interchange_overcharge_minor` |
| `fct_dispute` | days from sale to dispute, deadline state, merchant loss |
| `mart_auth_daily`, `mart_decline_reasons` | approval rates by any dimension; why declines happen |
| `mart_dispute_monitoring` | monthly ratio per merchant vs warning (0.65%) and excessive (0.90%, at least 10 disputes) thresholds; complete months only |
| `mart_dispute_cohort` | cumulative dispute rate by days since sale, per sales month |
| `mart_fee_economics` | volume, processor fees, interchange, scheme fees, margin and leakage per merchant and month |
| `mart_issuer_health`, `mart_auth_anomalies` | outage and card-testing detection |

Tests in `dbt/tests` prove the SQL rate card reproduces every standard interchange charge exactly, that downgrades always cost more, and that the daily approval mart accounts for every authorization once.

## Planted incidents
Recorded in `manifest.json` under `network.incidents`, never loaded into the warehouse:

1. **Issuer outage**: the busiest issuer answers `91` (issuer unavailable) for six hours; cardholders retry later.
2. **Card-testing attack**: 420 small online attempts on fresh cards in one hour at one merchant.
3. **Interchange downgrades**: 35% of one merchant's online payments miss the standard rate (+0.55%).
4. **Excessive disputes**: a high-risk (MCC 5967) merchant runs above the dispute threshold.

`tests/test_network.py` checks each one is found where it was planted and nowhere else, and that the API turns them into insights.

## Limits
Thresholds are modelled on network dispute-monitoring programmes but scaled to the synthetic volume (real programmes use far larger minimum counts). Rates, issuers and BINs are synthetic; codes follow public conventions.
