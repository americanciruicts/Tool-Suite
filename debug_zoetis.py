#!/usr/bin/env python3
"""
Debug Zoetis PDF extraction to understand why it returns 0 rows.
"""

import pdfplumber
import pandas as pd

pdf_path = "/home/tony/Compare Tool/Zoetis #8530 95011025-E BOM.pdf"

print("=" * 80)
print(f"Analyzing: {pdf_path}")
print("=" * 80)

with pdfplumber.open(pdf_path) as pdf:
    print(f"\nTotal pages: {len(pdf.pages)}")

    for page_num, page in enumerate(pdf.pages[:2], 1):
        print(f"\n--- Page {page_num} ---")

        # Extract text
        text = page.extract_text()
        if text:
            print(f"\nFirst 500 chars of text:")
            print(text[:500])

        # Extract tables
        tables = page.extract_tables()
        print(f"\nTables found: {len(tables)}")

        for table_idx, table in enumerate(tables, 1):
            print(f"\n  Table {table_idx}:")
            print(f"    Total rows: {len(table)}")

            if table and len(table) > 0:
                print(f"    Header (row 0): {table[0]}")

                # Show first 5 data rows
                print(f"\n    First 5 data rows:")
                for i, row in enumerate(table[1:6], 1):
                    print(f"      Row {i}: {row}")

                # Convert to DataFrame and show
                df = pd.DataFrame(table[1:], columns=table[0])
                print(f"\n    DataFrame shape: {df.shape}")
                print(f"    Columns: {list(df.columns)}")

                # Check for MPN-like columns
                print(f"\n    Looking for MPN column...")
                for col in df.columns:
                    if col:
                        col_lower = str(col).lower()
                        if any(kw in col_lower for kw in ['part', 'mpn', 'number', 'manufacturer']):
                            print(f"      Potential MPN column: '{col}'")
                            print(f"      First 5 values: {df[col].head().tolist()}")
