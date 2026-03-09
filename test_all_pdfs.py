#!/usr/bin/env python3
"""
Test all 14 provided PDFs.
"""

import sys
sys.path.insert(0, '/home/tony/Compare Tool/api')

from pdf_tool import extract_bom_from_pdf
import os
import glob

# Find all PDFs in the root directory
pdf_files = glob.glob("/home/tony/Compare Tool/*.pdf") + glob.glob("/home/tony/Compare Tool/*.PDF")

print(f"Found {len(pdf_files)} PDF files\n")

results = {
    'success': [],
    'failed': []
}

for pdf_path in sorted(pdf_files):
    filename = os.path.basename(pdf_path)
    print(f"Processing: {filename[:60]}...")

    try:
        output_path = pdf_path.replace('.pdf', '_EXTRACTED.xlsx').replace('.PDF', '_EXTRACTED.xlsx')
        result = extract_bom_from_pdf(pdf_path, output_path)

        print(f"  ✓ SUCCESS - {result['metadata']['rows_extracted']} rows, {result['metadata']['confidence']:.0%} confidence")
        results['success'].append({
            'filename': filename,
            'rows': result['metadata']['rows_extracted'],
            'confidence': result['metadata']['confidence'],
            'pages': result['metadata']['pages_processed'],
            'columns': len(result['metadata']['columns_detected'])
        })

    except Exception as e:
        print(f"  ✗ FAILED - {str(e)[:80]}")
        results['failed'].append({
            'filename': filename,
            'error': str(e)
        })

print(f"\n{'='*80}")
print(f"SUMMARY: {len(results['success'])}/{len(pdf_files)} PDFs successfully processed")
print(f"{'='*80}")

if results['success']:
    print(f"\n✓ Successful ({len(results['success'])}):")
    for r in results['success']:
        print(f"  - {r['filename'][:50]}: {r['rows']} rows, {r['confidence']:.0%} conf, {r['columns']} cols")

if results['failed']:
    print(f"\n✗ Failed ({len(results['failed'])}):")
    for r in results['failed']:
        print(f"  - {r['filename'][:50]}")
        print(f"    Error: {r['error'][:60]}")
