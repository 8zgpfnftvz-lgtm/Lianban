#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch the public Dabanke daily review pages used by the case cards.

The browser cannot read dabanke.com directly because the HTML response has no
CORS header. GitHub Actions runs this script server-side and writes the small
same-origin JSON file consumed by the PWA.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUTPUT = ROOT / "dabanke_data.json"
HOME = "https://www.dabanke.com/"
PAGE = "https://www.dabanke.com/index-{date}.html"
UA = "Tiantianban-PWA/1.0 (+https://www.dabanke.com/)"


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def request_text(url: str, timeout: int = 35) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, "replace")


def retry_text(url: str, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return request_text(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_error}")


def embedded_cases() -> list[dict]:
    source = INDEX.read_text(encoding="utf-8")
    line = next((x for x in source.splitlines() if x.startswith("let CASES=")), "")
    if not line:
        return []
    raw = line[len("let CASES="):].rstrip()
    if raw.endswith(";"):
        raw = raw[:-1]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def embedded_history() -> dict:
    source = INDEX.read_text(encoding="utf-8")
    line = next((x for x in source.splitlines() if x.startswith("const HIST=")), "")
    if not line:
        return {}
    raw = line[len("const HIST="):].rstrip()
    if raw.endswith(";"):
        raw = raw[:-1]
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def computed_case_symbols() -> dict[str, set[str]]:
    """Mirror computeCases() so the Action matches the page's current rules."""
    history = embedded_history()
    dates = history.get("dates") or []
    if not dates:
        return {}
    day_index = {date: i for i, date in enumerate(dates)}
    runs = []
    for row in history.get("runs") or []:
        if len(row) < 6 or row[4] not in day_index:
            continue
        ei = day_index[row[4]]
        lb = int(row[5])
        runs.append({
            "sym": row[0],
            "name": row[1],
            "ei": ei,
            "si": ei - lb + 1,
            "lb": lb,
        })

    active: dict[int, list[dict]] = {i: [] for i in range(len(dates))}
    for run in runs:
        for i in range(max(0, run["si"]), run["ei"] + 1):
            active[i].append({"run": run, "lb": i - run["si"] + 1})

    by_break: dict[int, list[dict]] = {}
    for run in runs:
        bi = run["ei"] + 1
        if run["lb"] >= 5 and bi < len(dates):
            by_break.setdefault(bi, []).append(run)

    result: dict[str, set[str]] = {}
    for bi, leaders in by_break.items():
        leaders = sorted(leaders, key=lambda x: x["lb"], reverse=True)
        lead = leaders[0]
        leader_syms = {x["sym"] for x in leaders}
        other_max = max(
            (
                stock["lb"]
                for stock in active.get(bi, [])
                if stock["run"]["sym"] not in leader_syms
            ),
            default=0,
        )
        if other_max >= lead["lb"]:
            continue
        wanted = {to_source_symbol(x["sym"]) for x in leaders}
        for stock in active.get(lead["ei"], []):
            if stock["lb"] >= 3 and stock["run"]["sym"] not in leader_syms:
                wanted.add(to_source_symbol(stock["run"]["sym"]))
        result.setdefault(dates[bi], set()).update(wanted)
    return result


def case_symbols(cases: list[dict]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for case in cases:
        day = case.get("breakDate")
        if not day:
            continue
        symbols = result.setdefault(day, set())
        leader = case.get("leader") or {}
        if leader.get("sym"):
            symbols.add(to_source_symbol(leader["sym"]))
        for stock in case.get("mids") or []:
            if stock.get("sym"):
                symbols.add(to_source_symbol(stock["sym"]))
    return result


def to_source_symbol(symbol: str) -> str:
    if re.match(r"^(sh|sz|bj)\d{6}$", symbol, re.I):
        return symbol[2:] + "." + symbol[:2].upper()
    return symbol


def parse_market(source: str) -> dict:
    market: dict = {}
    index_matches = re.findall(
        r'<div class="home-index-item\s+(?:is-rise|is-fall|is-flat)">\s*'
        r"<span>(.*?)</span>\s*<strong>(.*?)</strong>",
        source,
        re.S,
    )
    market["indices"] = [
        {"name": clean_text(name), "change": clean_text(change)}
        for name, change in index_matches
    ]

    note_match = re.search(
        r'<p class="home-market-overview-note">(.*?)</p>', source, re.S
    )
    if note_match:
        note_parts = re.findall(
            r"<strong>(.*?)</strong>|<span>(.*?)</span>", note_match.group(1), re.S
        )
        pieces = [clean_text(a or b) for a, b in note_parts]
        market["note"] = "；".join(x for x in pieces if x)

    cards: dict[str, dict] = {}
    for match in re.finditer(
        r'<article class="(is-[a-z-]+)">\s*<span>(.*?)</span>\s*'
        r"<strong>(.*?)</strong>\s*(?:<small[^>]*>(.*?)</small>)?",
        source,
        re.S,
    ):
        key, label, value, detail = match.groups()
        cards[key] = {
            "label": clean_text(label),
            "value": clean_text(value),
            "detail": clean_text(detail or ""),
        }
    market["limit"] = cards
    return market


def parse_stocks(source: str, wanted: set[str]) -> dict[str, dict]:
    if not wanted:
        return {}
    stocks: dict[str, dict] = {}
    tier_parts = re.split(r'<section class="ladder-view-tier"', source)[1:]
    for part in tier_parts:
        segment = part.split("</section>", 1)[0]
        tier_match = re.search(r"<h3>(.*?)</h3>", segment, re.S)
        ladder = clean_text(tier_match.group(1)) if tier_match else ""
        stock_parts = re.split(r'<div class="stock-line\s+', segment)[1:]
        for stock_part in stock_parts:
            symbol_match = re.search(
                r'data-symbol="([^"]+)"', stock_part[:600]
            )
            if not symbol_match:
                continue
            symbol = symbol_match.group(1).strip().upper()
            if symbol not in wanted:
                continue
            status_match = re.match(r"([a-z-]+)", stock_part)
            status_class = status_match.group(1) if status_match else ""
            name_match = re.search(
                r'class="stock-detail-link"[^>]*>(.*?)</a>', stock_part, re.S
            )
            change_match = re.search(
                r'<span class="stock-change[^"]*">(.*?)</span>',
                stock_part,
                re.S,
            )
            performance_match = re.search(
                r'<span class="ladder-tag ladder-performance[^"]*"[^>]*>(.*?)</span>',
                stock_part,
                re.S,
            )
            status_text = (
                clean_text(performance_match.group(1))
                if performance_match
                else ("未晋级" if status_class == "status-failed" else "")
            )
            stocks[symbol] = {
                "name": clean_text(name_match.group(1)) if name_match else "",
                "ladder": ladder,
                "change": clean_text(change_match.group(1)) if change_match else "",
                "status": (
                    "success"
                    if status_class == "status-success"
                    else "failed" if status_class == "status-failed" else status_class
                ),
                "statusText": status_text,
            }
    return stocks


def parse_day(date: str, source: str, wanted: set[str]) -> dict:
    market = parse_market(source)
    return {
        "date": date,
        "url": PAGE.format(date=date.replace("-", "")),
        "fetchedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "stockQueryComplete": True,
        "market": market,
        "stocks": parse_stocks(source, wanted),
    }


def latest_market_date() -> str:
    source = retry_text(HOME)
    match = re.search(
        r'<p class="home-market-meta">\s*<span>(\d{4}-\d{2}-\d{2})</span>',
        source,
        re.S,
    )
    if not match:
        raise RuntimeError("cannot find latest market date on homepage")
    return match.group(1)


def load_output() -> dict:
    if not OUTPUT.exists():
        return {"generatedAt": "", "source": HOME, "days": {}}
    try:
        value = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("days"), dict):
            for record in value["days"].values():
                if record.get("fetchedAt") and "stockQueryComplete" not in record:
                    record["stockQueryComplete"] = True
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return {"generatedAt": "", "source": HOME, "days": {}}


def save_output(data: dict) -> None:
    data["generatedAt"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    data["source"] = HOME
    data["days"] = dict(sorted(data["days"].items()))
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, OUTPUT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="fetch every case break date")
    parser.add_argument("--limit", type=int, default=0, help="fetch the latest N case dates")
    parser.add_argument("--latest", action="store_true", help="also fetch the latest market date")
    parser.add_argument("--date", action="append", default=[], help="fetch YYYY-MM-DD")
    parser.add_argument("--refresh", action="store_true", help="replace existing day records")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    wanted_by_day = computed_case_symbols()
    if not wanted_by_day:
        wanted_by_day = case_symbols(embedded_cases())
    case_dates = sorted(wanted_by_day)

    dates = set(args.date)
    if args.all:
        dates.update(case_dates)
    elif args.limit > 0:
        dates.update(case_dates[-args.limit:])
    if args.latest:
        dates.add(latest_market_date())
    if not dates:
        dates.add(latest_market_date())

    current = load_output()
    days = current.setdefault("days", {})
    pending = [
        d for d in sorted(dates)
        if (
            args.refresh
            or d not in days
            or not days[d].get("market")
            or (
                bool(wanted_by_day.get(d))
                and not days[d].get("stockQueryComplete")
            )
        )
    ]
    if not pending:
        print("No dates to fetch.")
        return 0

    print(f"Fetching {len(pending)} date(s) from dabanke.com with {args.workers} worker(s)...")

    def worker(date: str) -> tuple[str, dict | None, str | None]:
        url = PAGE.format(date=date.replace("-", ""))
        try:
            source = retry_text(url)
            record = parse_day(date, source, wanted_by_day.get(date, set()))
            return date, record, None
        except Exception as exc:
            return date, None, str(exc)

    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(worker, date): date for date in pending}
        for future in concurrent.futures.as_completed(futures):
            date, record, error = future.result()
            if record:
                days[date] = record
                print(f"  ok {date}: {len(record['stocks'])} stock row(s)")
            else:
                failures.append(date)
                print(f"  fail {date}: {error}", file=sys.stderr)

    if days:
        save_output(current)
        print(f"Wrote {OUTPUT} ({len(days)} day(s)).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
