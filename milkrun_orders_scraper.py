#!/usr/bin/env python3
"""Scrape your own MILKRUN order history from www.milkrun.com/my-account/my-orders.

The orders page requires you to be logged in, so this script drives a real
browser (Playwright + Chromium) with a persistent profile:

  * First run: a browser window opens; log in to MILKRUN when prompted, then
    press Enter in the terminal. Your session is saved to a local profile
    directory, so later runs won't ask again.
  * The script scrolls / clicks "load more" until every order is on the page,
    then parses each order card (status, order number, total, date/time).
  * With --details it also opens each order's "View details" page and captures
    the line items (best effort) plus the raw page text.

Results are written to milkrun_orders.csv and milkrun_orders.json.

Setup:
    pip install playwright
    playwright install chromium

Usage:
    python milkrun_orders_scraper.py                 # scrape the order list
    python milkrun_orders_scraper.py --details       # also scrape each order's items
    python milkrun_orders_scraper.py --max-orders 5  # only the 5 most recent
    python milkrun_orders_scraper.py --headless      # only once a login is saved

This is intended for exporting your *own* order history from your own account.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

ORDERS_URL = "https://www.milkrun.com/my-account/my-orders"

# "Order #26K4RPHONM4L"
ORDER_ID_RE = re.compile(r"^Order\s+#(?P<id>[A-Z0-9]+)\s*$")
# "Order Delivered", "Order Cancelled", ... (the status badge above the order number)
STATUS_RE = re.compile(r"^Order\s+(?!#)(?P<status>[A-Za-z][A-Za-z ]+?)\s*$")
# "$142.19 on 15 Jul at 03:16 pm"
PRICE_DATE_RE = re.compile(
    r"^\$(?P<total>[\d,]+(?:\.\d{2})?)\s+on\s+(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3,})"
    r"(?:\s+(?P<year>\d{4}))?\s+at\s+(?P<time>\d{1,2}:\d{2})\s*(?P<ampm>[ap]m)\s*$",
    re.IGNORECASE,
)
# Best-effort line item on a detail page: "Full Cream Milk 2L   $3.50"
ITEM_RE = re.compile(r"^(?P<name>[^$]{3,}?)\s+\$(?P<price>[\d,]+\.\d{2})\s*$")
QTY_RE = re.compile(r"^(?:Qty:?\s*)?(?P<qty>\d{1,3})\s*(?:x|×)?\s*$", re.IGNORECASE)


@dataclass
class Order:
    order_id: str
    status: str
    total: float | None
    ordered_at: str  # ISO 8601, e.g. "2026-07-15T15:16:00"
    ordered_at_raw: str  # the text as shown on the page
    detail_url: str = ""
    items: list[dict] = field(default_factory=list)
    detail_text: str = ""


def parse_order_datetime(day: str, month: str, year: str | None, time_s: str, ampm: str,
                         now: datetime | None = None) -> str:
    """Turn '15', 'Jul', None, '03:16', 'pm' into an ISO timestamp.

    The page omits the year on recent orders, so assume the current year and
    roll back one year if that would put the order in the future.
    """
    now = now or datetime.now()
    month = month[:3].title()
    fmt = "%d %b %Y %I:%M %p"
    if year:
        return datetime.strptime(f"{day} {month} {year} {time_s} {ampm.upper()}", fmt).isoformat()
    dt = datetime.strptime(f"{day} {month} {now.year} {time_s} {ampm.upper()}", fmt)
    if dt > now + timedelta(days=1):
        dt = dt.replace(year=now.year - 1)
    return dt.isoformat()


def parse_orders_from_text(body_text: str, now: datetime | None = None) -> list[Order]:
    """Parse order cards out of the rendered page text.

    Each card renders as consecutive lines like:
        Order Delivered
        Order #26K4RPHONM4L
        $142.19 on 15 Jul at 03:16 pm
        View details
    Parsing the text instead of CSS classes keeps this resilient to restyling.
    """
    lines = [ln.strip() for ln in body_text.splitlines()]
    orders: list[Order] = []
    for i, line in enumerate(lines):
        id_match = ORDER_ID_RE.match(line)
        if not id_match:
            continue

        status = ""
        for prev in reversed(lines[max(0, i - 3):i]):
            if not prev:
                continue
            status_match = STATUS_RE.match(prev)
            if status_match:
                status = status_match.group("status").strip()
            break

        total: float | None = None
        ordered_at = ""
        ordered_at_raw = ""
        for nxt in lines[i + 1:i + 4]:
            pd = PRICE_DATE_RE.match(nxt)
            if pd:
                ordered_at_raw = nxt
                total = float(pd.group("total").replace(",", ""))
                try:
                    ordered_at = parse_order_datetime(
                        pd.group("day"), pd.group("month"), pd.group("year"),
                        pd.group("time"), pd.group("ampm"), now=now,
                    )
                except ValueError:
                    ordered_at = ""
                break

        orders.append(Order(
            order_id=id_match.group("id"),
            status=status,
            total=total,
            ordered_at=ordered_at,
            ordered_at_raw=ordered_at_raw,
        ))
    return orders


def parse_items_from_text(detail_text: str) -> list[dict]:
    """Best-effort extraction of line items from an order detail page.

    Looks for "<product name>  $<price>" lines, picking up an adjacent
    quantity line when one exists. The raw page text is saved alongside, so
    nothing is lost if the layout doesn't match these patterns.
    """
    items: list[dict] = []
    lines = [ln.strip() for ln in detail_text.splitlines() if ln.strip()]
    skip_words = ("total", "subtotal", "delivery", "service fee", "discount",
                  "refund", "gst", "payment", "order #")
    for i, line in enumerate(lines):
        m = ITEM_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if any(w in name.lower() for w in skip_words):
            continue
        qty = 1
        for neighbour in (lines[i - 1] if i > 0 else "", lines[i + 1] if i + 1 < len(lines) else ""):
            q = QTY_RE.match(neighbour)
            if q:
                qty = int(q.group("qty"))
                break
        items.append({
            "name": name,
            "quantity": qty,
            "price": float(m.group("price").replace(",", "")),
        })
    return items


def count_orders_on_page(page) -> int:
    return len(ORDER_ID_RE.findall(page.inner_text("body"), ))


def wait_for_login(page) -> None:
    """If the orders page isn't showing (session expired / first run), let the
    user log in manually in the visible browser window."""
    try:
        page.wait_for_selector("text=/Order #/", timeout=15_000)
        return
    except PlaywrightTimeoutError:
        pass

    body = page.inner_text("body").lower()
    if "you haven't placed any orders" in body or "no orders" in body:
        return

    print("\nIt looks like you're not logged in (or the page hasn't loaded).")
    print("Log in to MILKRUN in the browser window, navigate to My Orders,")
    input("then come back here and press Enter to continue... ")
    page.goto(ORDERS_URL)
    page.wait_for_selector("text=/Order #/", timeout=30_000)


def load_all_orders(page, max_orders: int | None) -> None:
    """Scroll (and click any load-more button) until the order count stops growing."""
    stable_rounds = 0
    last_count = count_orders_on_page(page)
    while stable_rounds < 3:
        if max_orders is not None and last_count >= max_orders:
            return
        page.mouse.wheel(0, 4000)
        for label in ("Load more", "Show more", "See more"):
            button = page.get_by_role("button", name=re.compile(label, re.IGNORECASE))
            if button.count() and button.first.is_visible():
                button.first.click()
                break
        page.wait_for_timeout(1_500)
        count = count_orders_on_page(page)
        stable_rounds = stable_rounds + 1 if count == last_count else 0
        last_count = count


def scrape_details(page, orders: list[Order]) -> None:
    """Open each order's "View details" page and capture items + raw text."""
    for index, order in enumerate(orders):
        buttons = page.get_by_role("button", name=re.compile("View details", re.IGNORECASE))
        if not buttons.count():
            buttons = page.get_by_text(re.compile("View details", re.IGNORECASE))
        if index >= buttons.count():
            print(f"  ! No 'View details' button found for order {order.order_id}; skipping")
            continue
        print(f"  fetching details for order #{order.order_id} ({index + 1}/{len(orders)})")
        buttons.nth(index).click()
        try:
            page.wait_for_selector(f"text=#{order.order_id}", timeout=15_000)
        except PlaywrightTimeoutError:
            page.wait_for_timeout(3_000)
        page.wait_for_timeout(1_000)
        order.detail_url = page.url
        order.detail_text = page.inner_text("body")
        order.items = parse_items_from_text(order.detail_text)
        page.goto(ORDERS_URL)
        page.wait_for_selector("text=/Order #/", timeout=30_000)
        load_all_orders(page, max_orders=len(orders))
        time.sleep(0.5)  # be gentle with the site


def write_outputs(orders: list[Order], base: Path, include_detail_text: bool) -> None:
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")

    payload = []
    for order in orders:
        record = asdict(order)
        if not include_detail_text:
            record.pop("detail_text")
        payload.append(record)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["order_id", "status", "total", "ordered_at", "ordered_at_raw",
                         "num_items", "detail_url"])
        for order in orders:
            writer.writerow([order.order_id, order.status, order.total, order.ordered_at,
                             order.ordered_at_raw, len(order.items) or "", order.detail_url])

    print(f"\nWrote {len(orders)} orders to {json_path} and {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export your MILKRUN order history.")
    parser.add_argument("--details", action="store_true",
                        help="also open each order's detail page and capture line items")
    parser.add_argument("--max-orders", type=int, default=None,
                        help="stop after this many orders (most recent first)")
    parser.add_argument("--headless", action="store_true",
                        help="run without a browser window (only works once a login is saved)")
    parser.add_argument("--profile-dir", default=str(Path.home() / ".milkrun-scraper-profile"),
                        help="browser profile dir that stores your login session")
    parser.add_argument("--output", default="milkrun_orders",
                        help="output file base name (writes <name>.csv and <name>.json)")
    args = parser.parse_args()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            args.profile_dir,
            headless=args.headless,
            viewport={"width": 1400, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        print(f"Opening {ORDERS_URL} ...")
        page.goto(ORDERS_URL, wait_until="domcontentloaded")
        wait_for_login(page)
        load_all_orders(page, args.max_orders)

        orders = parse_orders_from_text(page.inner_text("body"))
        if args.max_orders is not None:
            orders = orders[:args.max_orders]
        print(f"Found {len(orders)} orders")

        if args.details and orders:
            scrape_details(page, orders)

        context.close()

    if not orders:
        print("No orders found — if the browser showed a login page, run again "
              "without --headless and log in when prompted.")
        return 1

    write_outputs(orders, Path(args.output), include_detail_text=args.details)
    return 0


if __name__ == "__main__":
    sys.exit(main())
