"""Build an inline result dashboard from recorded samples and actual simulator fills."""
import argparse
import html
import json
from collections import defaultdict
from pathlib import Path


def build(report_path, output):
    report = json.loads(Path(report_path).read_text())
    samples = report.get("samples") or []
    fills = report.get("fill_events")
    if not samples or fills is None:
        raise ValueError("Need recorded samples and actual fill_events; rerun --demo --cycles 1000 --report FILE")
    limits = report["limits"]
    volume, notional = defaultdict(int), defaultdict(float)
    for fill in fills:
        iid = fill["instrument"]
        volume[iid] += fill["volume"]
        notional[iid] += fill["price"] * fill["volume"]
    total = sum(volume.values())
    peak = samples[0]["pnl"]
    pnl_rows, dd_rows, exposure_rows, capacity_rows = [], [], [], []
    for s in samples:
        peak = max(peak, s["pnl"])
        pnl_rows.append([s["cycle"], s["pnl"]])
        dd_rows.append([s["cycle"], s["pnl"] - peak])
        exposure_rows.append([s["cycle"], sum(abs(p * s["marks"][i]) for i, p in s["positions"].items())])
        capacity_rows.append([s["cycle"], max((abs(p) / limits[i] for i, p in s["positions"].items()), default=0)])
    assert len({s["cycle"] for s in samples}) == len(samples)
    assert abs(samples[-1]["pnl"] - report["pnl"]) < 1e-8
    assert all(0 <= v <= 1 for _, v in capacity_rows), "Observed position limit breach"

    def config(iid, title, rows, unit, height=185, percent=False):
        return json.dumps({"id": iid, "title": title, "showHeader": False,
                           "height": height, "columns": ["轮次", "值"], "rows": rows,
                           "spec": {"type": "line", "x": "轮次", "y": "值",
                                    "xLabel": "轮次", "yLabel": unit, "showLegend": False,
                                    "startAtZero": True, "colors": {"值": "var(--chart-1)"},
                                    "valueFormat": {"style": "percent" if percent else "decimal",
                                                    "maximumFractionDigits": 2}}}, ensure_ascii=False).replace("<", "\\u003c")

    replacements = {
        "PNL": config("pnl", "策略累计 PNL", pnl_rows, "PNL", 280),
        "DD": config("drawdown", "回撤", dd_rows, "PNL"),
        "EXPOSURE": config("exposure", "持仓名义总敞口", exposure_rows, "价格×股数"),
        "CAPACITY": config("capacity", "最高单产品持仓占用", capacity_rows, "占限额比例", percent=True),
        "SUBTITLE": f'{samples[-1]["cycle"]:,} 轮 · {len(samples):,} 个逐轮采样点 · {len(fills):,} 笔实际模拟成交 · 与原运行独立重跑',
    }
    stats = [("累计 PNL", f'{report["pnl"]:+,.2f}', "模拟价格单位"),
             ("最大回撤", f'{min(v for _, v in dd_rows):,.2f}', "相对此前 PNL 峰值"),
             ("累计成交量", f'{total:,}', "手 · 双边均计入"),
             ("累计成交名义额", f'{sum(notional.values()):,.2f}', "价格 × 成交量")]
    replacements["STATS"] = "".join(f'<div class="stat"><span class="text-small text-muted">{a}</span><strong>{b}</strong><span class="text-small text-muted">{c}</span></div>' for a, b, c in stats)
    aliases = {"SEMIS_ETF_US": "ETF US", "SEMIS_ETF_EU": "ETF EU"}
    short = lambda i: html.escape(aliases.get(i, i))
    tiles = []

    def treemap(items, x=0, y=0, width=100, height=100):
        if not items:
            return
        if len(items) == 1:
            iid, v = items[0]
            label = f'{short(iid)} · {v / total:.1%}'
            visible = f'<span>{label}</span>' if width > 25 and height > 18 else ''
            tiles.append(f'<div class="tile" style="left:{x:.6f}%;top:{y:.6f}%;width:calc({width:.6f}% - 2px);height:calc({height:.6f}% - 2px)" data-tooltip="{html.escape(iid)}: {v:,} 手，{v / total:.2%}">{visible}</div>')
            return
        total_value = sum(v for _, v in items)
        split = min(range(1, len(items)), key=lambda j: abs(sum(v for _, v in items[:j]) - total_value / 2))
        share = sum(v for _, v in items[:split]) / total_value
        # Account for the panel's approximate aspect ratio when partitioning.
        if width * 1.2 >= height:
            treemap(items[:split], x, y, width * share, height)
            treemap(items[split:], x + width * share, y, width * (1 - share), height)
        else:
            treemap(items[:split], x, y, width, height * share)
            treemap(items[split:], x, y + height * share, width, height * (1 - share))

    ordered = sorted(volume.items(), key=lambda item: item[1], reverse=True)
    treemap(ordered)
    replacements["TREEMAP"] = "".join(tiles)
    replacements["VOLUME_LIST"] = "".join(f'<span>{short(i)} {v / total:.1%}</span>' for i, v in ordered)
    replacements["VOLUME_ALT"] = html.escape("；".join(f'{i}: {v} 手，占 {v / total:.1%}' for i, v in ordered))
    rows = []
    last = samples[-1]
    for iid in limits:
        avg = f'{notional[iid] / volume[iid]:.4f}' if volume[iid] else "—"
        position = last["positions"].get(iid, 0)
        mark = last["marks"][iid]
        rows.append(f'<tr><td>{html.escape(iid)}</td><td class="text-end">{avg}</td><td class="text-end">{position:+,}</td><td class="text-end">{mark:.4f}</td><td class="text-end">{position * mark:+,.2f}</td></tr>')
    replacements["POSITIONS"] = "".join(rows)
    forecasts = []
    threshold = report["forecast_max_error"]
    for iid, forecasts_by_side in report.get("forecasts", {}).items():
        bid, ask = forecasts_by_side.get("bid"), forecasts_by_side.get("ask")
        error = max((p["error"] for p in forecasts_by_side.values()), default=None)
        bid_text = f'{bid["price"]:.4f}' if bid else "—"
        ask_text = f'{ask["price"]:.4f}' if ask else "—"
        error_text = f'{error:.4f}' if error is not None else "—"
        verdict = "可用" if error is not None and error <= threshold else "忽略" if error is not None else "无样本"
        forecasts.append(f'<tr><td>{html.escape(iid)}</td><td class="text-end">{bid_text}</td><td class="text-end">{ask_text}</td><td class="text-end">{error_text}</td><td>{verdict}</td></tr>')
    replacements["FORECASTS"] = "".join(forecasts)
    replacements["FORECAST_NOTE"] = f'期末快照，MAE 阈值 {threshold:g}；策略实际使用还受行情新鲜度限制。'
    replacements["RESIDUAL"] = '剩余成分股对冲敞口（股）：' + ' · '.join(f'{html.escape(i)} {v:+.2f}' for i, v in report["constituent_exposures"].items())
    source = Path(__file__).with_name("visualization_template.html").read_text()
    for key, value in replacements.items():
        source = source.replace("__" + key + "__", value)
    if "__" in source:
        raise ValueError("Unresolved template placeholder")
    Path(output).write_text(source)
    print(f'Built {output}: {len(samples)} samples, {len(fills)} fills, PNL={report["pnl"]:.2f}, drawdown={min(v for _, v in dd_rows):.2f}')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--output", default="trading-results.html")
    args = parser.parse_args()
    build(args.report, args.output)
