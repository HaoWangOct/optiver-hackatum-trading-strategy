# Optiver HackaTUM 2024 — ETF Arbitrage & Market Making

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#quick-start)
[![Tests](https://img.shields.io/badge/Tests-unittest-informational)](#testing)
[![Status](https://img.shields.io/badge/Status-post--event_reconstruction-orange)](#project-provenance)

> **Post-event reconstruction / educational research project.** This is **not** a recovered copy of the original HackaTUM submission, the winning team's implementation, or a verified profitable strategy. The original SSH environment and code were lost. This repository recreates the concepts using the challenge statement, retained example-trader snippets/logs, public Optibook API patterns and an independently developed simulation.

## Challenge

The *Transistor Trading* challenge on Optibook involved five tradable products: dual-listed ETFs and their underlying constituents. The objective was to exploit temporary price discrepancies between ETF listings and between an ETF and its basket, manage different exchange opening hours, and potentially quote less-liquid products.

**Focus:** quantitative research · statistical arbitrage · order-book modelling · inventory risk · Python engineering.

## Strategy architecture

```text
Market snapshots (synthetic / future Optibook adapter)
        │
        ├── Basket fair value ──────────┐
        ├── Cross-listing executable edge├──> Signal / execution decision
        └── Rolling Fourier forecast ──┘         │
                                                  ▼
                                     Position / notional limits
                                                  │
                                                  ▼
                                     Simulated fills + PnL
```

| Module | What it does |
| --- | --- |
| `src/pricing.py` | Mid and executable bid/ask basket values (long/short directions differ) |
| `src/strategy.py` | Cross-listed ETF and ETF-versus-basket signals, inventory-skewed two-sided quotes |
| `src/risk.py` | Proposed position-limit and gross-exposure checks |
| `src/forecast.py` | Optional bounded rolling-window Fourier extrapolation |
| `src/simulator.py` | Small conservative toy market with transaction costs, positions and marked-to-market equity |
| `demo.py` | Deterministic example using **illustrative** products, weights and prices |
| `tests/` | Unit tests for arbitrage directions, pricing, risk and forecasts |

### Relative value

For weights `w_i`, the indicative basket mid is `Σ w_i mid_i`. **Executable** basket values are different: buying the basket pays the constituents' asks; selling it receives their bids. A buy-ETF/sell-basket trade requires:

```text
basket executable bid − ETF ask > costs + safety buffer
```

The reverse direction requires `ETF bid − basket executable ask > costs + buffer`. Cross-listed ETFs use analogous bid/ask comparisons. This avoids the false arbitrage signals caused by comparing mid-prices alone.

### Inventory-aware market making

A simplified reservation price is `fair_value − inventory_penalty × position`. Bid/ask quotes are tick-rounded away from the midpoint, with a configurable spread. The simulator does **not** claim to model queue priority, adverse selection, or all exchange rules.

### Fourier research extension

A fixed-size sliding window isolates a small set of dominant frequencies after demeaning. This is an **experimental feature**, motivated by the *publicly described* strategy ideas of Team-054, not a recreation of their private >1,500-line code. Predictions should be assessed out of sample and benchmarked against a no-change forecast; no trading edge is established here.

## Quick start

No broker, API key, external credentials, or Optibook server required.

```bash
python -m pip install -r requirements.txt
python demo.py
python -m unittest discover -s tests -v
```

The example dataset is entirely **synthetic**. No historical Optibook data, actual ETF definitions, transaction fees or challenge-specific position limits are included. Replace illustrative weights and multipliers with documented contract specifications before any realistic evaluation.

## Project provenance

- **From the retained challenge notes:** five products; two ETF listings, constituent arbitrage and exchange-opening effects.
- **From retained personal notes:** sample Optibook `Exchange` API code; basic bid/ask quoting and PnL logs.
- **Public inspiration (not source code):** Team-054 described FFT-style short-term forecasts, weighted basket valuation, two-sided quoting, hedging and stock-limit constraints.
- **Newly written in this repository:** offline pricing engine, risk checks, signals, synthetic simulator, examples and tests.
- **Not provided:** original event source code, historical order books, authentic benchmark returns, championship code or competition ranking.

## Roadmap

- [x] Transparent reconstruction and synthetic pricing/signal tests
- [ ] Confirm exact 2024 instrument specifications and ETF conversion factors
- [ ] Write an optional, credential-free Optibook adapter (never commit `~/.optibook` or passwords)
- [ ] Add multi-leg execution/partial-fill and market-hours model
- [ ] Backtest with permitted historical data and report realized PnL, drawdown, turnover and prediction error
- [ ] Compare baseline strategy with Fourier-enhanced signals out of sample

## References

- [Optiver / Optibook HackaTUM challenge site](https://hackatum.optibook.net) (historical; availability may change)
- [Public Optibook example trader](https://github.com/MiniHacks/dubious_bot/blob/master/example1.py)
- [Community Optibook basket challenge example](https://github.com/jonathan-ih/optibook_basket_challenge)
- [Team-054 public project write-up](https://devpost.com/software/seismicspecialists)

---

**Hao Wang** · [GitHub](https://github.com/HaoWangOct) · [Email](mailto:ge32zul@tum.de)

*Research / portfolio demonstration only. Not investment advice or a live trading system.*
