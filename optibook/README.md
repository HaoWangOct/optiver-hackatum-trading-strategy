# Official Optibook SDK

This directory documents the SDK location used in the reference repository's layout. It intentionally contains no `__init__.py`, client implementation, account configuration, or credentials.

Install the official SDK supplied with your Optibook competition environment. An installed regular `optibook` package takes precedence over this documentation-only namespace directory. Do not infer SDK availability from this directory's presence, and do not install an unrelated similarly named PyPI package.

Keep the provider's connection settings in `~/.optibook` and verified strategy parameters in the ignored root `config.json`. Then run:

```bash
python3 bot.py --engine optibook --inspect
python3 example1.py --engine optibook
python3 bot.py --engine optibook --config config.json --cycles 20
```

These commands inspect or dry-run the official environment. Sending competition orders additionally requires `--live` and a verified configuration. No real Optibook credentials are included in this project.

The default `python3 bot.py --engine rtg` path uses the separate free Ready Trader Go runtime and does not need this SDK.
