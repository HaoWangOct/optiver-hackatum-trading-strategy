# Transistor Trading

An Optibook strategy project with ETF arbitrage, bounded Fourier forecasts, inventory-aware quoting, an offline simulator, and a results dashboard. It also integrates the freely downloadable historical **Optiver Ready Trader Go** template for local ETF/future replay.

Python 3.9 or later is required. The offline simulator and headless Ready Trader Go integration use only the Python standard library. Connecting to Optibook requires the competition-provided SDK, credentials, and verified product specifications.

## Run the free Ready Trader Go template

The runner downloads the original template archive published by the HackMelbourne teaching project and verifies its pinned SHA-256 checksum. It uses the template's matching engine, fee rules, and sample market data without modifying their source. See [THIRD_PARTY.md](THIRD_PARTY.md) for provenance and licensing.

```bash
# Download and verify the runtime; internet access is required on first use.
python3 run_ready_trader_go.py --setup

# Smoke test: replay the first 60 seconds of sample data at 10x speed.
python3 run_ready_trader_go.py --duration 60 --speed 10

# Replay the complete one-hour sample at 50x speed.
python3 run_ready_trader_go.py --speed 50
```

Each match runs two participants:

- **FourierTrader:** quotes the ETF using the future, inventory adjustments, and bounded background Fourier forecasts. It hedges confirmed fills, retries partial hedges, and retains order reservations until cancellation is acknowledged. Pending exposure, rejected orders, and position limits restrict new quotes.
- **TemplateBaseline:** the original, unmodified example autotrader from the downloaded archive.

This environment trades **one ETF and its future**. The five-product, dual-listed ETF/basket strategy remains in `trading.py`; it is not run in the two-product environment. A Ready Trader Go replay does not establish a connection to official Optibook.

### Recorded replay result

One complete replay of `market_data.csv`, covering 3,600 simulation seconds at 50x speed, produced:

| Participant | Final PNL | Maximum drawdown | Rule breaches |
| --- | ---: | ---: | ---: |
| FourierTrader | -145.63 | -464.00 | 0 |
| TemplateBaseline | -17,246.79 | -17,404.57 | 0 |

Both strategies lost money. This single sample comparison does not establish statistical superiority or live profitability. Different data, machine timing, and replay speeds can change the result. The engine's monetary outputs are divided by 100 when exported from cents.

The committed [replay summary](rtg_match_summary.json) records the source, checksum, settings, results, and local run directory. Each match writes files under `rtg_runs/<timestamp>/`; `rtg_runs/latest.txt` points to the most recent successful match:

- `score_board.csv`: engine-recorded PNL, fees, positions, and status.
- `match_events.csv`: replay orders, fills, and hedge events.
- `summary.json`: final PNL, sampled maximum positions, drawdown, traded lots, and breaches.
- `exchange.log`, `fourier_trader.log`, and `baseline.log`: runtime diagnostics.

The runner checks that both participants reached the end of the selected data and treats a rule breach as failure. Downloaded source, sample data, and raw run files remain outside version control.

## Run the five-product offline simulator

```bash
python3 trading.py --demo --cycles 100
python3 trading.py --demo --cycles 1000 --report demo_result.json
python3 -m unittest discover -s tests -v
```

The synthetic simulator exercises the strategy's actual order logic against five sample products, changing prices, and simulated takers. It deliberately includes pricing discrepancies to test execution and risk handling. It does not model real network latency, queue priority, complete exchange rules, or competing teams, and its results are not a live-market backtest.

`--report` records the initial state and each completed cycle's PNL, positions, marks, and constituent exposures. Synthetic runs also record actual simulator fills. Recording adds API reads and is enabled only when a report is requested; non-demo reports require a finite `--cycles` value.

## View the dashboard

Open the included `trading-dashboard.html` in a browser. It contains synthetic five-product results, **not the Ready Trader Go replay results**. Charts require internet access to load their pinned rendering runtime.

To regenerate the chart fragment from a new recorded synthetic run:

```bash
python3 trading.py --demo --cycles 1000 --report visualization_result.json
python3 visualize_results.py visualization_result.json
```

The generator writes `trading-results.html`, an embeddable visualization fragment. The standalone `trading-dashboard.html` is an included browser preview; regenerating the fragment does not automatically replace that preview.

The dashboard shows cumulative PNL, traded-volume shares, drawdown, gross position notional, position-limit utilization, final positions, and forecast diagnostics. Drawdown is the absolute difference from the preceding PNL peak. Notional amounts use simulator price units. Without starting capital, the dashboard does not invent account equity, percentage returns, or a probabilistic Sharpe ratio.

The synthetic simulator uses wall-clock reservations and background forecasting, so independent runs can differ slightly. Older `demo_result.json` files without per-cycle samples cannot reconstruct a full curve.

## Five-product strategy

1. **Dual-listed ETF arbitrage:** compare the executable ask on one listing with the executable bid on the other. Send IOC orders only when the expected edge exceeds `min_edge` after fees.
2. **Basket relative value:** use `ETF = cash_component + sum(weight * stock_price)`. Buy-ETF/sell-basket plans use constituent bids; the reverse uses constituent asks. Rational weights determine exact integer hedge lots: weights `0.5, 0.3, 0.2` imply `10 ETF : 5, 3, 2 shares`. Skip plans whose required lots exceed order limits.
3. **Fourier forecasts:** seed from `get_trade_tick_history()` once, then ingest `poll_new_trade_ticks()` incrementally. Separate prices and volumes by aggressor side, resample onto an equal-time grid, detrend, retain bounded DFT frequencies, and extrapolate one sample. A fixed 128-sample window bounds computation. Validate the final eight points using predictions fitted only to preceding observations. Ignore stale or inaccurate forecasts; eligible forecasts make small price adjustments and cap quoted volume. Buyer-initiated trades consume the ask, while seller-initiated trades consume the bid. These forecasts concern executed trades, not full order-book depth.
4. **Two-sided quoting:** quote the wider-spread ETF using the basket or other listing, prediction adjustments, and inventory skew. Keep quotes passive and constrain their edge and size using the same hedge route used after execution. Refresh quotes on a configured interval and cancel them on exit.
5. **Partial-fill reconciliation:** send subsequent legs according to observed first-leg fills. Reconcile `stock_position + total_etf_position * weight` on later cycles. Cancel passive quotes and prioritize hedging when at least one share remains unhedged. Retain fractional-share residuals rather than repeatedly trading around them.
6. **Closed markets:** check `paused`, configurable UTC sessions, and book timestamps. Never execute constituent arbitrage against a closed stock's stale book. Dual-listing opportunities remain available when both ETFs trade. Optional `allow_closed_quoting` uses the other open ETF as the anchor with wider quotes. Existing constituent inventory restricts this mode. Cached NAV has an expiry and does not represent a live valuation of closed stocks.

Only the trading thread calls the synchronous Exchange client. The background thread handles calculations; both the data window and frequency count are bounded. This project independently implements the described ideas and does not reproduce another team's private code or guarantee its reported accuracy.

## Connect to Optibook

Use the official SDK installation supplied with the competition VM. Keep credentials in the competition environment's `~/.optibook` and real strategy parameters in local `config.json`; these files and run logs are ignored by Git.

Start with read-only discovery on the VM:

```bash
python3 trading.py --inspect
cp config.example.json config.json
```

`--inspect` lists instrument IDs, tick sizes, paused states, and missing SDK methods. Before enabling orders, configure:

- The actual two ETF and three constituent IDs. The challenge's example IDs are not sufficient to establish the real semiconductor universe; placeholders remain intentional.
- `weights` as **shares per ETF unit**, converting percentage weights, divisors, multipliers, or currency effects into the actual contract formula. Weights need not sum to one.
- Equivalent ETF contracts in the same currency with the same basket and units. Other conversion ratios require extending pricing and hedge calculations before trading.
- Competition-specific ticks, position limits, order sizes, fees, request limits, and session-loss limits. Example values are illustrative.
- Daily `sessions_utc`, such as `[["08:00", "16:30"], ["18:00", "20:00"]]`. Overnight sessions are supported; an empty array relies on `paused`. Accelerated exchange clocks and special calendars require an appropriate clock/status adapter.
- An API budget appropriate to the official SDK. The current implementation conservatively paces all calls through `requests_per_second`; `cycle_seconds` is an inter-cycle pause, not total cycle latency.

Set `verified` to `true` only after checking these parameters. It is a local guard against accidentally using the example configuration.

Observe signals without submitting or cancelling orders:

```bash
python3 trading.py --config config.json --cycles 20
```

Explicitly enable competition-account orders:

```bash
python3 trading.py --config config.json --live
```

The live account should be dedicated to this strategy. Startup and shutdown cancel all outstanding orders in configured products, including manual orders. Interrupts, a loss stop, and exceptions attempt cancellation across those products; they do not flatten positions. Check exchange-side state after connection failures.

## Execution limits and validation

Risk checks include observed positions, same-side outstanding orders, accepted limits not yet visible on the information channel, and conservative short-lived IOC reservations. Cancellation must be acknowledged before replacements are inserted. Status and books are refreshed before execution.

`settlement_seconds` controls the first fill-observation delay; `ioc_reservation_seconds` controls IOC reservation expiry. Information-channel lag must be assessed in the real environment. Late fills can still affect hedge decisions and risk estimates. Multi-leg execution is not atomic: prices can change, hedge legs can fail or partially fill, and the logged expected edge is not realized profit. Basket relative-value trades may depend on later convergence when no creation/redemption facility exists. The loss stop measures PNL against the value at this process's startup.

Tests cover price ticks, overnight sessions, reservations, quoting and cancellations, partial fills, exact basket lots, market closures, stale books, dry runs, order rejection, loss stops, forecast bounds, metrics recording, and end-to-end simulation. Downloading the RTG runtime additionally enables protocol tests and a headless engine smoke test in CI.

The original five-product adapter has not been validated against an actual Optibook account. Confirm SDK compatibility and product specifications using discovery and dry-run mode in the competition environment.
