#!/usr/bin/env python3
"""
Debug the Series ambiguity error.
"""

import sys
sys.path.insert(0, '/home/tony/Compare Tool/api')

import traceback

# Test one of the failing PDFs
pdf_path = "/home/tony/Compare Tool/Elliot Electric 10-Pin Comms Cable..pdf"

try:
    from pdf_tool import extract_bom_from_pdf
    output_path = pdf_path.replace('.pdf', '_DEBUG.xlsx')
    result = extract_bom_from_pdf(pdf_path, output_path)
    print("Success!")
except Exception as e:
    print(f"Error: {e}")
    print("\nFull traceback:")
    traceback.print_exc()
