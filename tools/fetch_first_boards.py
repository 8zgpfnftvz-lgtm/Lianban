#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build first-board data with the same sources as Tiantianban.

First boards come from Eastmoney's limit-up pool. Themes and limit-up
reasons come from Kaipanla's DailyLimitResumption endpoint. Existing
historical records remain available with their original source metadata.
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
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
OUTPUT = ROOT / "first_board_data.json"
HOME = "https://www.dabanke.com/"
PAGE = "https://www.dabanke.com/index-{date}.html"
UA = "Tiantianban-PWA/1.0 (+https://www.dabanke.com/)"
POOL_API = "https://push2ex.eastmoney.com/getTopicZTPool"
KPL_API = "https://apphwhq.longhuvip.com/w1/api/index.php"
KPL_UA = "Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)"


def beijing_today() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()


def format_market_symbol(code: str, market: int) -> str:
    code = str(code or "").zfill(6)
    if code.startswith(("4", "8", "92")):
        return "bj" + code
    if market == 1 or code.startswith(("6", "9")):
        return "sh" + code
    return "sz" + code


def format_bar_time(value) -> str:
    text = str(int(value or 0)).zfill(6)
    return text[:2] + ":" + text[2:4] + ":" + text[4:] if len(text) == 6 else ""


def fetch_eastmoney_pool(day: str) -> tuple[str, list[dict]]:
    query = urllib.parse.urlencode({
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "pagesize": "1000",
        "sort": "fbt:asc",
        "date": day.replace("-", ""),
    })
    request = urllib.request.Request(
        POOL_API + "?" + query,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    data = payload.get("data") or {}
    pool = data.get("pool") or []
    qdate = str(data.get("qdate") or "")
    if len(qdate) != 8 or not pool:
        raise RuntimeError("东方财富涨停池为空")
    actual = qdate[:4] + "-" + qdate[4:6] + "-" + qdate[6:]
    return actual, pool


def fetch_kpl_reasons(day: str) -> tuple[str, dict[str, dict]]:
    params = {
        "a": "GetPlateInfo_w38",
        "st": "100",
        "c": "DailyLimitResumption",
        "PhoneOSNew": "1",
        "DeviceID": "tiantianban-desktop",
        "VerSion": "5.21.0.2",
        "Index": "0",
        "apiv": "w42",
        "Day": day,
    }
    request = urllib.request.Request(
        KPL_API,
        data=urllib.parse.urlencode(params).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": KPL_UA,
            "Connection": "Keep-Alive",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    stocks = {}
    for group in payload.get("list") or []:
        group_name = str(group.get("ZSName") or "").strip()
        for row in group.get("StockList") or []:
            if not isinstance(row, list) or len(row) < 18:
                continue
            code = str(row[0] or "").zfill(6)
            if len(code) != 6:
                continue
            symbol = format_market_symbol(code, 0)
            theme = str(row[16] or "").strip()
            if not theme or theme in ("-", "其他"):
                theme = group_name if group_name and group_name != "其他" else ""
            stocks[symbol] = {
                "name": str(row[1] or "").strip(),
                "theme": theme,
                "reason": theme or group_name,
                "detail": str(row[17] or "").strip(),
                "concepts": str(row[11] or "").strip(),
            }
    return str(payload.get("date") or ""), stocks


def fetch_eastmoney_day(requested_day: str, allow_latest: bool = False) -> tuple[str, dict]:
    actual_day, pool = fetch_eastmoney_pool(requested_day)
    if not allow_latest and actual_day != requested_day:
        raise RuntimeError(f"涨停池日期未对齐：请求 {requested_day}，返回 {actual_day}")
    reasons_day, reason_map = {}, {}
    try:
        reasons_day, reason_map = fetch_kpl_reasons(actual_day)
    except Exception:
        pass
    reasons_aligned = reasons_day == actual_day
    first_rows = []
    all_reasons = {}
    for item in pool:
        code = str(item.get("c") or "").zfill(6)
        market = int(item.get("m") or 0)
        symbol = format_market_symbol(code, market)
        boards = max(1, int(item.get("lbc") or 1))
        kpl = reason_map.get(symbol, {}) if reasons_aligned else {}
        theme = kpl.get("theme") or str(item.get("hybk") or "").strip() or "其他"
        reason = kpl.get("reason") or theme
        detail = kpl.get("detail") or ""
        all_reasons[symbol] = {
            "name": str(item.get("n") or "").strip(),
            "boards": boards,
            "theme": theme,
            "reason": reason,
            "detail": detail,
            "reasonSource": "开盘啦" if kpl else "行业",
        }
        if boards != 1:
            continue
        first_rows.append({
            "sym": symbol,
            "name": str(item.get("n") or "").strip(),
            "theme": theme,
            "reason": reason,
            "reasonDetail": detail,
            "reasonSource": "开盘啦" if kpl else "行业",
            "change": ("+" if float(item.get("zdp") or 0) > 0 else "") +
                f"{float(item.get('zdp') or 0):.2f}%",
            "status": "success",
            "statusText": "封板",
            "firstTime": format_bar_time(item.get("fbt")),
            "lastTime": format_bar_time(item.get("lbt")),
            "opens": int(item.get("zbc") or 0),
            "fund": float(item.get("fund") or 0),
            "turnover": float(item.get("hs") or 0),
            "industry": str(item.get("hybk") or "").strip(),
        })
    source = "东方财富涨停池 + 开盘啦 DailyLimitResumption"
    if not reasons_aligned:
        source += "（开盘啦日期未对齐，原因用行业兜底）"
    return actual_day, {
        "date": actual_day,
        "requestedDate": requested_day,
        "source": source,
        "sourceMode": "eastmoney",
        "reasonsAligned": reasons_aligned,
        "fetchedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "sealed": len(first_rows),
        "total": len(first_rows),
        "rate": "",
        "stocks": first_rows,
        "reasons": all_reasons,
    }


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


def parse_ladder_reasons(source: str) -> dict:
    reasons = {}
    for section in source.split('<section class="ladder-view-tier"')[1:]:
        section = section.split("</section>", 1)[0]
        heading = re.search(r"<h3>(首板|\d+进(\d+))</h3>", section)
        if not heading:
            continue
        boards = 1 if heading.group(1) == "首板" else int(heading.group(2))
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
            reasons[symbol] = {
                "name": clean_text(name_match.group(1)) if name_match else header.group(2),
                "boards": boards,
                "theme": theme,
                "reason": reason or theme,
            }
    return reasons


def parse_day(date: str, source: str) -> dict:
    record = parse_first_board(source)
    record.update({
        "date": date,
        "url": PAGE.format(date=date.replace("-", "")),
        "fetchedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "reasons": parse_ladder_reasons(source),
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
        return {"generatedAt": "", "source": "东方财富涨停池 + 开盘啦", "days": {}}
    try:
        value = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("days"), dict):
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return {"generatedAt": "", "source": "东方财富涨停池 + 开盘啦", "days": {}}


def save_output(data: dict) -> None:
    data["generatedAt"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    data["source"] = "东方财富涨停池 + 开盘啦"
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
        dates.add(beijing_today())
    if not dates:
        dates.add(beijing_today())

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
            actual, record = fetch_eastmoney_day(
                date,
                allow_latest=bool(args.latest and date == beijing_today()),
            )
            return actual, record, None
        except Exception as exc:
            return date, None, str(exc)

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(worker, date): date for date in pending}
        for future in concurrent.futures.as_completed(futures):
            date, record, error = future.result()
            if record:
                days[date] = record
                print(
                    f"  ok {date}: {len(record['stocks'])} first-board stock(s), "
                    f"{len(record.get('reasons') or {})} reason sample(s)"
                )
            else:
                failures.append(date)
                print(f"  fail {date}: {error}", file=sys.stderr)

    if days:
        save_output(data)
        print(f"Wrote {OUTPUT} ({len(days)} day(s)).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
