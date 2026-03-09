#!/usr/bin/env python3
"""
Comprehensive debug of all PDFs to understand their structure.
"""

import pdfplumber
import pandas as pd
import glob
import re

def analyze_pdf(pdf_path):
    """Analyze a single PDF and return info about its structure."""
    result = {
        'filename': pdf_path.split('/')[-1][:50],
        'pages': 0,
        'tables_found': 0,
        'text_lines': 0,
        'has_bom_keywords': False,
        'table_structure': None,
        'text_sample': None
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            result['pages'] = len(pdf.pages)

            # Check first page
            if pdf.pages:
                page = pdf.pages[0]

                # Extract text
                text = page.extract_text()
                if text:
                    lines = text.split('\n')
                    result['text_lines'] = len(lines)

                    # Check for BOM keywords
                    text_lower = text.lower()
                    bom_keywords = ['item', 'part number', 'mpn', 'manufacturer', 'description', 'qty', 'quantity', 'ref des']
                    found_kw = [kw for kw in bom_keywords if kw in text_lower]
                    result['has_bom_keywords'] = len(found_kw) >= 3
                    result['keywords_found'] = found_kw

                    # Get first few lines
                    result['text_sample'] = lines[:5]

                # Extract tables
                tables = page.extract_tables()
                result['tables_found'] = len(tables)

                if tables:
                    table = tables[0]
                    result['table_rows'] = len(table)
                    result['table_cols'] = len(table[0]) if table else 0
                    result['table_header'] = table[0] if table else None

                    # Check data distribution
                    if len(table) > 1:
                        data_row = table[1]
                        non_empty = sum(1 for c in data_row if c and str(c).strip())
                        result['data_cols_with_values'] = non_empty
                        result['first_data_row'] = data_row

    except Exception as e:
        result['error'] = str(e)

    return result


# Find all PDFs
pdf_files = glob.glob("/home/tony/Compare Tool/*.pdf") + glob.glob("/home/tony/Compare Tool/*.PDF")

print(f"Analyzing {len(pdf_files)} PDFs...\n")

for pdf_path in sorted(pdf_files):
    result = analyze_pdf(pdf_path)

    print(f"{'='*80}")
    print(f"File: {result['filename']}")
    print(f"Pages: {result['pages']}, Tables: {result['tables_found']}, Text lines: {result['text_lines']}")
    print(f"Has BOM keywords: {result['has_bom_keywords']}")

    if result.get('keywords_found'):
        print(f"Keywords: {result['keywords_found']}")

    if result.get('table_header'):
        print(f"Table header: {result['table_header'][:5]}...")  # First 5 columns
        print(f"Table size: {result.get('table_rows')} rows x {result.get('table_cols')} cols")
        print(f"Data cols with values: {result.get('data_cols_with_values')}")

    if result.get('text_sample'):
        print(f"Text sample:")
        for line in result['text_sample'][:3]:
            print(f"  {line[:80]}")

    if result.get('error'):
        print(f"ERROR: {result['error']}")

    print()
