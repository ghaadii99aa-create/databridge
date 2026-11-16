"""Generate the SAMPLE retail sales dataset used in the DataBridge demonstration.

All values are synthetic and generated from a fixed seed, so the file is reproducible.
Data quality problems are injected deliberately and counted at the end, so the quality
engine's findings can be checked against a known answer.

Usage:  python scripts/generate_sample_data.py
Output: sample_data/retail_sales_sample.csv and sample_data/retail_sales_sample.xlsx
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_data"
SEED = 20260115
ROWS = 2400

CATALOG = {
    "Electronics": [("Wireless Earbuds", 249.0), ("27-inch Monitor", 1099.0), ("USB-C Hub", 129.0),
                    ("Laptop Stand", 159.0), ("Smart Watch", 899.0)],
    "Home & Kitchen": [("Coffee Grinder", 189.0), ("Air Fryer", 399.0), ("Knife Set", 279.0),
                       ("Storage Containers", 69.0)],
    "Apparel": [("Cotton Thobe", 220.0), ("Running Shoes", 349.0), ("Winter Jacket", 459.0), ("Abaya", 380.0)],
    "Grocery": [("Arabic Coffee 500g", 45.0), ("Dates Box 1kg", 85.0), ("Olive Oil 1L", 39.0), ("Basmati Rice 5kg", 62.0)],
    "Sports & Outdoors": [("Yoga Mat", 99.0), ("Camping Tent", 649.0), ("Dumbbell Pair", 210.0)],
    "Beauty": [("Oud Perfume", 520.0), ("Skincare Set", 240.0), ("Hair Dryer", 310.0)],
}
CATEGORY_VARIANTS = {
    "Electronics": ["electronics", "ELECTRONICS", "Electronics "],
    "Home & Kitchen": ["Home and Kitchen", "home & kitchen", "Home &  Kitchen"],
    "Sports & Outdoors": ["Sports-Outdoors", "sports & outdoors"],
    "Apparel": ["apparel"],
}
SEGMENTS = [("Consumer", 0.55), ("Small Business", 0.28), ("Corporate", 0.17)]
REGIONS = [("Central", 0.34), ("Western", 0.27), ("Eastern", 0.22), ("Southern", 0.10), ("Northern", 0.07)]
CHANNELS = [("Online", 0.58), ("In-Store", 0.42)]
HEADER = ["Transaction ID", "Transaction Date", "Product Category", "Product Name", "Quantity",
          "Unit Price (SAR)", "Revenue (SAR)", "Customer Segment", "Region", "Sales Channel"]


def weighted(rng: random.Random, options: list[tuple[str, float]]) -> str:
    return rng.choices([o for o, _ in options], weights=[w for _, w in options])[0]


def main() -> None:
    rng = random.Random(SEED)
    start = date(2025, 1, 1)
    rows: list[list[str]] = []
    injected = {"category_variants": 0, "missing_segment": 0, "missing_revenue": 0, "negative_qty": 0,
                "invalid_qty": 0, "alt_date_format": 0, "duplicates": 0, "whitespace_region": 0,
                "bulk_orders": 0}

    for i in range(ROWS):
        day = start + timedelta(days=int(rng.triangular(0, 364, 300)))
        category = rng.choice(list(CATALOG))
        product, base_price = rng.choice(CATALOG[category])
        price = round(base_price * rng.uniform(0.92, 1.05), 2)
        qty = max(1, int(rng.expovariate(1 / 2.2)) + 1)
        if rng.random() < 0.006:
            qty = rng.randint(80, 150)
            injected["bulk_orders"] += 1
        revenue = round(qty * price, 2)

        date_text = day.isoformat()
        if rng.random() < 0.06:
            date_text = day.strftime("%m/%d/%Y")
            injected["alt_date_format"] += 1
        cat_text = category
        if category in CATEGORY_VARIANTS and rng.random() < 0.07:
            cat_text = rng.choice(CATEGORY_VARIANTS[category])
            injected["category_variants"] += 1
        segment = weighted(rng, SEGMENTS)
        if rng.random() < 0.04:
            segment = rng.choice(["", "N/A"])
            injected["missing_segment"] += 1
        qty_text = str(qty)
        if rng.random() < 0.008:
            qty_text = str(-qty)
            revenue = -revenue
            injected["negative_qty"] += 1
        elif rng.random() < 0.004:
            qty_text = rng.choice(["two", "3 units", "?x"])
            injected["invalid_qty"] += 1
        revenue_text = f"{revenue:.2f}"
        if rng.random() < 0.025:
            revenue_text = ""
            injected["missing_revenue"] += 1
        region = weighted(rng, REGIONS)
        if rng.random() < 0.02:
            region = f" {region} "
            injected["whitespace_region"] += 1

        rows.append([f"TXN-{100001 + i}", date_text, cat_text, product, qty_text, f"{price:.2f}",
                     revenue_text, segment, region, weighted(rng, CHANNELS)])

    # exact duplicates: the same transaction exported twice
    for _ in range(48):
        rows.insert(rng.randrange(len(rows)), list(rng.choice(rows)))
        injected["duplicates"] += 1

    OUT.mkdir(exist_ok=True)
    csv_path = OUT / "retail_sales_sample.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        writer.writerows(rows)

    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Sales"
        ws.append(HEADER)
        for r in rows:
            ws.append(r)
        wb.save(OUT / "retail_sales_sample.xlsx")
    except ImportError:
        print("openpyxl not installed; skipped .xlsx")

    print(f"SAMPLE DATA written: {csv_path} ({len(rows)} rows)")
    for k, v in injected.items():
        print(f"  injected {k}: {v}")


if __name__ == "__main__":
    main()
