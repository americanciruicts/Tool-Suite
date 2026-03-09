#!/usr/bin/env python3
"""
Quick analysis script to understand the structure of the sample PDFs.
"""

import pdfplumber
import sys
import os

def analyze_pdf(pdf_path):
    """Analyze a PDF and show its table structure."""
    print(f"\n{'='*80}")
    print(f"Analyzing: {os.path.basename(pdf_path)}")
    print(f"{'='*80}")

    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"Total pages: {len(pdf.pages)}")

            # Analyze first 2 pages
            for page_num, page in enumerate(pdf.pages[:2], 1):
                print(f"\n--- Page {page_num} ---")

                # Extract text sample
                text = page.extract_text()
                if text:
                    lines = text.split('\n')[:10]
                    print(f"First 10 lines of text:")
                    for i, line in enumerate(lines, 1):
                        print(f"  {i:2d}: {line[:100]}")

                # Extract tables
                tables = page.extract_tables()
                print(f"\nTables found: {len(tables)}")

                for table_idx, table in enumerate(tables, 1):
                    print(f"\n  Table {table_idx}:")
                    print(f"    Rows: {len(table)}")
                    print(f"    Columns: {len(table[0]) if table else 0}")

                    if table and len(table) > 0:
                        print(f"    Header row: {table[0]}")

                        if len(table) > 1:
                            print(f"    First data row: {table[1]}")

                        if len(table) > 2:
                            print(f"    Second data row: {table[2]}")

    except Exception as e:
        print(f"Error analyzing PDF: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    # Analyze a few sample PDFs
    pdf_files = [
        "/home/tony/Compare Tool/Electroswitch #7183 01-0510-0010 BOM_MFR LIST.PDF",
        "/home/tony/Compare Tool/DEHN #8797 500-0144-000 REV-C00_0001  Part# 3031380.pdf",
        "/home/tony/Compare Tool/Jorge #5518 05050006 rev- BOM.pdf",
    ]

    for pdf_file in pdf_files:
        if os.path.exists(pdf_file):
            analyze_pdf(pdf_file)
        else:
            print(f"File not found: {pdf_file}")
