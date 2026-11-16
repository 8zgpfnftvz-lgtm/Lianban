#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch recent 3+ board ladders from Dabanke daily pages."""

from __future__ import annotations

import argparse
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
OUTPUT = ROOT / "lianban_snapshot.json"
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


def source_symbol(value: str) -> str:
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", value.strip(), re.I)
    if not match:
        return ""
    return match.group(2).lower() + match.group(1)


def parse_ladders(source: str) -> list[dict]:
    stocks = []
    for section in source.split('<section class="ladder-view-tier"')[1:]:
        section = section.split("</section>", 1)[0]
        heading = re.search(r"<h3>(\d+)进(\d+)</h3>", section)
        if not heading:
            continue
        boards = int(heading.group(2))
        if boards < 3:
            continue
        for part in section.split('<div class="stock-line ')[1:]:
            header = re.match(r'([a-z-]+)"\s+data-symbol="([^"]+)"', part)
            if not header or header.group(1) != "status-success":
                continue
            symbol = source_symbol(header.group(2))
            if not symbol:
                continue
            name_match = re.search(
                r'class="stock-detail-link"[^>]*>(.*?)</a>',
                part,
                re.S,
            )
            reason_match = re.search(
                r'<details class="ladder-stock-reason">\s*<summary[^>]*>(.*?)</summary>\s*<p>(.*?)</p>',
                part,
                re.S,
            )
            theme = clean_text(reason_match.group(1)) if reason_match else ""
            reason = clean_text(re.sub(
                r"<small.*?</small>",
                " ",
                reason_match.group(2) if reason_match else "",
                flags=re.S,
            ))
            stocks.append({
                "sym": symbol,
                "name": clean_text(name_match.group(1)) if name_match else header.group(2),
                "boards": boards,
                "theme": theme,
                "reason": reason or theme,
            })
    return stocks


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
    parser.add_argument("--latest", action="store_true", help="fetch the latest market date")
    parser.add_argument("--date", action="append", default=[], help="fetch YYYY-MM-DD")
    parser.add_argument("--refresh", action="store_true", help="replace existing day records")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dates = set(args.date)
    if args.latest or not dates:
        dates.add(latest_market_date())
    data = load_output()
    days = data.setdefault("days", {})
    failures = False
    for date in sorted(dates):
        if date in days and not args.refresh:
            continue
        try:
            source = retry_text(PAGE.format(date=date.replace("-", "")))
            record = {
                "date": date,
                "url": PAGE.format(date=date.replace("-", "")),
                "fetchedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                "stocks": parse_ladders(source),
            }
            days[date] = record
            print(f"  ok {date}: {len(record['stocks'])} ladder stock(s)")
        except Exception as exc:
            failures = True
            print(f"  fail {date}: {exc}", file=sys.stderr)
    if days:
        save_output(data)
        print(f"Wrote {OUTPUT} ({len(days)} day(s)).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
