# Ready Trader Go source and provenance

- Competition and original documentation: https://readytradergo.optiver.com/
- Public release mirror: https://github.com/HackMelbourne/Optiver_RTG_Workshop/releases/tag/1.0
- Original template asset: `pyready_trader_go_pyside6_au_fixed.zip`
- SHA-256: `0e06e853eb2d64f47fe66a2b5d5e2c36e3c75106c7fd9e8fc088894dd4c4bd78`
- The archive contains Optiver's copyright notices and GNU AGPL version 3-or-later notices. A copy of its supplied license is retained in `licenses/Ready-Trader-Go-AGPL-3.0.txt`.

The downloadable runtime and its historical sample datasets are stored under ignored `external/`. Each match gets its own copy under ignored `rtg_runs/`, including the original copyright headers and license. The matching engine and original baseline autotrader are unmodified. Match configuration changes only select sample data, loopback port, team names, start delay and replay speed.

`rtg_autotrader.py` is a new integration under AGPL-3.0-or-later that subclasses the template protocol. It trades one ETF and hedges with its future, using actual execution acknowledgements. It reuses this project's bounded Fourier forecasting module; it is not a submission copied from a competing team. `run_ready_trader_go.py` downloads, verifies and launches the runtime without importing its optional Qt GUI.

This integration is a local historical replay. It neither supplies nor bypasses access credentials for official Optibook. Its ETF/future universe differs from the five-product Transistor Trading challenge.

## Repository layout reference

The flat layout with `bot.py`, `helper.py`, `colors.py`, examples, and two notebooks is inspired by https://github.com/MiniHacks/dubious_bot. These entry points and notebooks were written for this project. No strategy source or bundled Optibook SDK was copied from that repository. The documentation-only `optibook/` directory explains how to obtain the official competition SDK separately.
