"""Download the free RTG template and run its engine without GUI dependencies."""
import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
URL = "https://github.com/HackMelbourne/Optiver_RTG_Workshop/releases/download/1.0/pyready_trader_go_pyside6_au_fixed.zip"
SHA256 = "0e06e853eb2d64f47fe66a2b5d5e2c36e3c75106c7fd9e8fc088894dd4c4bd78"
RUNTIME = ROOT / "external/ready-trader-go/pyready_trader_go_pyside6"


def setup_runtime():
    if (RUNTIME / "ready_trader_go/exchange.py").is_file():
        return RUNTIME
    archive = ROOT / "external/ready-trader-go/template.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    print("Downloading public Ready Trader Go template...", flush=True)
    urllib.request.urlretrieve(URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Template checksum mismatch")
    with ZipFile(archive) as z:
        for info in z.infolist():
            if not (archive.parent / info.filename).resolve().is_relative_to(archive.parent.resolve()):
                raise ValueError("Unsafe archive path")
        z.extractall(archive.parent)
    return RUNTIME


def worker(name):
    if name == "exchange":
        from ready_trader_go.exchange import main
        main()
    else:
        from ready_trader_go.trader import main
        main(name)


def summarize(directory, speed, source, started):
    with (directory / "score_board.csv").open() as f:
        scores = list(csv.DictReader(f))
    with (directory / "match_events.csv").open() as f:
        events = [r for r in csv.DictReader(f) if r["Competitor"]]
    teams = {}
    for row in scores:
        name = row["Team"]
        stats = teams.setdefault(name, {"pnl": [], "max_abs_etf": 0, "max_abs_future": 0, "breaches": 0})
        stats["pnl"].append([float(row["Time"]), float(row["ProfitOrLoss"]) / 100])
        stats["max_abs_etf"] = max(stats["max_abs_etf"], abs(int(row["EtfPosition"])))
        stats["max_abs_future"] = max(stats["max_abs_future"], abs(int(row["FuturePosition"])))
        stats["breaches"] += row["Operation"] == "Breach"
        stats["last"] = row
    for name, stats in teams.items():
        fills = [r for r in events if r["Competitor"] == name and r["Operation"] in ("Trade", "Hedge")]
        peak, drawdown = 0, 0
        for _, pnl in stats["pnl"]:
            peak = max(peak, pnl)
            drawdown = min(drawdown, pnl - peak)
        last = stats.pop("last")
        stats.update(final_pnl=float(last["ProfitOrLoss"]) / 100,
                     final_etf_position=int(last["EtfPosition"]),
                     final_future_position=int(last["FuturePosition"]),
                     total_fees=float(last["TotalFees"]) / 100,
                     final_time=float(last["Time"]), max_drawdown=drawdown,
                     fills=len(fills), traded_lots=sum(int(r["Volume"]) for r in fills))
    result = {"engine": "Optiver Ready Trader Go (downloaded public 2021 template)",
              "template_url": URL, "template_sha256": SHA256,
              "market_data": source, "speed": speed, "wall_seconds": time.monotonic() - started,
              "teams": teams, "note": "Local ETF/future replay; not a connection to official Optibook."}
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({name: {k: v for k, v in values.items() if k != "pnl"}
                      for name, values in teams.items()}, indent=2))
    if set(teams) != {"FourierTrader", "TemplateBaseline"} or any(s["breaches"] for s in teams.values()):
        raise RuntimeError("Missing participant or a trading-rule breach; see match logs")
    return result


def run(speed=20.0, dataset="market_data.csv", duration=None):
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("Speed must be finite and positive")
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("Duration must be finite and positive")
    runtime = setup_runtime()
    directory = ROOT / "rtg_runs" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True)
    for name in ("ready_trader_go",):
        shutil.copytree(runtime / name, directory / name)
    for source, dest in ((runtime / "autotrader.py", "baseline.py"),
                         (ROOT / "rtg_autotrader.py", "fourier_trader.py"),
                         (ROOT / "forecast.py", "forecast.py")):
        shutil.copy2(source, directory / dest)
    shutil.copy2(runtime / "COPYING.txt", directory / "COPYING.txt")
    config = json.loads((runtime / "exchange.json").read_text())
    source = runtime / "data" / dataset
    if not source.resolve().is_relative_to((runtime / "data").resolve()) or not source.is_file():
        raise ValueError("Choose a market data CSV from the template data directory")
    # Optional prefix for smoke tests; no invented or regenerated market events.
    expected_end = 0.0
    if duration is not None:
        selected = directory / "market_data.csv"
        with source.open() as f, selected.open("w") as out:
            out.write(next(f))
            for line in f:
                stamp = float(line.split(",", 1)[0])
                if stamp > duration:
                    break
                expected_end = stamp
                out.write(line)
        source = selected
    else:
        with source.open() as f:
            next(f)
            for line in f:
                if line.strip():
                    expected_end = float(line.split(",", 1)[0])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config["Execution"] = {"Host": "127.0.0.1", "Port": port}
    config.pop("Hud", None)
    config["Engine"].update(MarketDataFile=str(source), Speed=float(speed), MarketOpenDelay=2.0)
    config["Traders"] = {"FourierTrader": "local-simulation", "TemplateBaseline": "local-simulation"}
    (directory / "exchange.json").write_text(json.dumps(config, indent=2))
    for module, team in (("fourier_trader", "FourierTrader"), ("baseline", "TemplateBaseline")):
        trader_config = {"Execution": config["Execution"], "Information": config["Information"],
                         "TeamName": team, "Secret": "local-simulation"}
        (directory / f"{module}.json").write_text(json.dumps(trader_config, indent=2))
    print(f"Running original RTG matching engine in {directory}", flush=True)
    environment = dict(os.environ, PYTHONPATH=str(directory))
    processes, handles = [], []
    started = time.monotonic()
    try:
        for name in ("exchange", "fourier_trader", "baseline"):
            if name != "exchange":
                # The information file is created before the market opens.
                deadline = time.monotonic() + 10
                while not (directory / "info.dat").exists():
                    if processes[0].poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("RTG engine did not start; see exchange.stdout.log")
                    time.sleep(.05)
            handle = (directory / f"{name}.stdout.log").open("w")
            handles.append(handle)
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", name],
                                       cwd=directory, env=environment, stdout=handle, stderr=subprocess.STDOUT)
            processes.append(process)
        processes[0].wait(timeout=max(60, expected_end / speed * 3 + 20))
        if processes[0].returncode:
            raise RuntimeError("RTG exchange process failed; see exchange.stdout.log")
        for process in processes[1:]:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
            if process.returncode:
                raise RuntimeError("An autotrader process failed; see its stdout log")
        result = summarize(directory, speed, dataset + (f" (first {duration}s)" if duration else ""), started)
        if min(t["final_time"] for t in result["teams"].values()) < expected_end - 1:
            raise RuntimeError("A trader stopped before the replay completed")
        (ROOT / "rtg_runs/latest.txt").write_text(str(directory) + "\n")
        return directory
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=5)
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--dataset", default="market_data.csv")
    parser.add_argument("--duration", type=float, help="Smoke-test prefix length in simulation seconds")
    parser.add_argument("--worker", choices=["exchange", "fourier_trader", "baseline"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
    elif args.setup:
        print(setup_runtime())
    else:
        print("Run directory:", run(args.speed, args.dataset, args.duration))
