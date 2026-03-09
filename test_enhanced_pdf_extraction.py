#!/usr/bin/env python3
"""
Test the enhanced PDF extraction with real sample PDFs.
"""

import sys
sys.path.insert(0, '/home/tony/Compare Tool/api')

from pdf_tool import extract_bom_from_pdf
import os

# Test PDFs
test_pdfs = [
    "/home/tony/Compare Tool/Jorge #5518 05050006 rev- BOM.pdf",
    "/home/tony/Compare Tool/Electroswitch #7183 01-0510-0010 BOM_MFR LIST.PDF",
    "/home/tony/Compare Tool/DEHN #8797 500-0144-000 REV-C00_0001  Part# 3031380.pdf",
]

for pdf_path in test_pdfs:
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        continue

    print(f"\n{'='*80}")
    print(f"Testing: {os.path.basename(pdf_path)}")
    print(f"{'='*80}")

    try:
        output_path = pdf_path.replace('.pdf', '_EXTRACTED.xlsx').replace('.PDF', '_EXTRACTED.xlsx')

        result = extract_bom_from_pdf(pdf_path, output_path)

        print(f"✓ Success!")
        print(f"  Pages processed: {result['metadata']['pages_processed']}")
        print(f"  Rows extracted: {result['metadata']['rows_extracted']}")
        print(f"  Confidence: {result['metadata']['confidence']:.1%}")
        print(f"  Columns detected: {', '.join(result['metadata']['columns_detected'])}")
        print(f"  Output file: {output_path}")

        if result['warnings']:
            print(f"  Warnings:")
            for warning in result['warnings']:
                print(f"    - {warning}")

    except Exception as e:
        print(f"✗ Failed: {e}")
        import traceback
        traceback.print_exc()
