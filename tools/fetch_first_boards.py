#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build first-board history from Dabanke daily review pages."""

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
OUTPUT = ROOT / "first_board_data.json"
HOME = "https://www.dabanke.com/"
PAGE = "https://www.dabanke.com/index-{date}.html"
UA = "Tiantianban-PWA/1.0 (+https://www.dabanke.com/)"


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def request_text(url: str, timeout: int = 35) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
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


def embedded_dates() -> list[str]:
    source = INDEX.read_text(encoding="utf-8")
    marker = "const HIST="
    start = source.index(marker) + len(marker)
    history, _ = json.JSONDecoder().raw_decode(source[start:].lstrip())
    return list(history.get("dates") or [])


def source_symbol(value: str) -> str:
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", value.strip(), re.I)
    if not match:
        return ""
    return match.group(2).lower() + match.group(1)


def parse_first_board(source: str) -> dict:
    matches = list(re.finditer(
        r'<section class="ladder-view-tier"[^>]*aria-label="首板股票">',
        source,
    ))
    if not matches:
        return {"sealed": 0, "total": 0, "rate": "", "stocks": []}
    segment = source[matches[-1].start():].split("</section>", 1)[0]
    heading = re.search(r"<h3>首板</h3>\s*<strong>(.*?)</strong>\s*<p>(.*?)</p>", segment, re.S)
    rate = clean_text(heading.group(1)) if heading else ""
    summary = clean_text(heading.group(2)) if heading else ""
    count = re.search(r"封住\s*(\d+)\s*/\s*(\d+)", summary)
    sealed = int(count.group(1)) if count else 0
    total = int(count.group(2)) if count else 0

    stocks = []
    for part in segment.split('<div class="stock-line ')[1:]:
        header = re.match(r'([a-z-]+)"\s+data-symbol="([^"]+)"', part)
        if not header:
            continue
        status_class, raw_symbol = header.groups()
        symbol = source_symbol(raw_symbol)
        if not symbol:
            continue
        name_match = re.search(
            r'class="stock-detail-link"[^>]*>(.*?)</a>',
            part,
            re.S,
        )
        change_match = re.search(
            r'<span class="stock-change[^"]*">(.*?)</span>',
            part,
            re.S,
        )
        performance = re.search(
            r'class="ladder-tag ladder-performance[^"]*"([^>]*)>(.*?)</span>',
            part,
            re.S,
        )
        performance_title = ""
        performance_text = ""
        if performance:
            title_match = re.search(r'title="([^"]*)"', performance.group(1))
            performance_title = clean_text(title_match.group(1)) if title_match else ""
            performance_text = clean_text(performance.group(2))
        first_time_match = re.search(r"首封\s*(\d{2}:\d{2}:\d{2})", performance_title)
        opens_match = re.search(r"开板\s*(\d+)\s*次", performance_title)

        theme_match = re.search(
            r'<details class="ladder-stock-reason">\s*<summary[^>]*>(.*?)</summary>\s*<p>(.*?)</p>',
            part,
            re.S,
        )
        theme = clean_text(theme_match.group(1)) if theme_match else ""
        reason_html = theme_match.group(2) if theme_match else ""
        reason = clean_text(re.sub(r"<small.*?</small>", " ", reason_html, flags=re.S))
        stocks.append({
            "sym": symbol,
            "name": clean_text(name_match.group(1)) if name_match else raw_symbol,
            "theme": theme,
            "reason": reason or theme,
            "change": clean_text(change_match.group(1)) if change_match else "",
            "status": (
                "success"
                if status_class == "status-success"
                else "opened"
                if status_class == "status-opened"
                else "failed"
            ),
            "statusText": performance_text or ("封板" if status_class == "status-success" else "开板"),
            "firstTime": first_time_match.group(1) if first_time_match else "",
            "opens": int(opens_match.group(1)) if opens_match else 0,
        })
    if not total:
        total = len(stocks)
    if not sealed:
        sealed = sum(stock["status"] == "success" for stock in stocks)
    return {"sealed": sealed, "total": total, "rate": rate, "stocks": stocks}


def parse_day(date: str, source: str) -> dict:
    record = parse_first_board(source)
    record.update({
        "date": date,
        "url": PAGE.format(date=date.replace("-", "")),
        "fetchedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    })
    return record


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
    parser.add_argument("--all", action="store_true", help="fetch every embedded trading date")
    parser.add_argument("--since", help="fetch embedded dates on or after YYYY-MM-DD")
    parser.add_argument("--latest", action="store_true", help="fetch the latest market date")
    parser.add_argument("--limit", type=int, default=0, help="fetch the latest N embedded dates")
    parser.add_argument("--date", action="append", default=[], help="fetch YYYY-MM-DD")
    parser.add_argument("--refresh", action="store_true", help="replace existing day records")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    embedded = embedded_dates()
    dates = set(args.date)
    if args.all:
        dates.update(embedded)
    elif args.since:
        dates.update(date for date in embedded if date >= args.since)
    elif args.limit > 0:
        dates.update(embedded[-args.limit:])
    if args.latest:
        dates.add(latest_market_date())
    if not dates:
        dates.add(latest_market_date())

    data = load_output()
    days = data.setdefault("days", {})
    pending = [
        date for date in sorted(dates)
        if args.refresh or date not in days
    ]
    if not pending:
        print("No first-board dates to fetch.")
        return 0

    print(f"Fetching {len(pending)} first-board date(s) with {args.workers} worker(s)...")

    def worker(date: str) -> tuple[str, dict | None, str | None]:
        try:
            source = retry_text(PAGE.format(date=date.replace("-", "")))
            record = parse_day(date, source)
            return date, record, None
        except Exception as exc:
            return date, None, str(exc)

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(worker, date): date for date in pending}
        for future in concurrent.futures.as_completed(futures):
            date, record, error = future.result()
            if record:
                days[date] = record
                print(f"  ok {date}: {len(record['stocks'])} first-board stock(s)")
            else:
                failures.append(date)
                print(f"  fail {date}: {error}", file=sys.stderr)

    if days:
        save_output(data)
        print(f"Wrote {OUTPUT} ({len(days)} day(s)).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
