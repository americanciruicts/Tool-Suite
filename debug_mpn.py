#!/usr/bin/env python3
"""
Debug script to test MPN normalization and comparison logic
"""

import pandas as pd
import os
import sys

# Add the api directory to the path so we can import excel_tool
sys.path.append('api')
from excel_tool import find_header_row_and_map, compare_boms

def debug_mpn_normalization():
    """Debug the MPN normalization process"""
    
    # Test files from the user's screenshot
    file1_path = "test_files/motherboard BOM.xls"
    file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
    
    print("=== MPN Normalization Debug ===")
    print(f"File 1: {file1_path}")
    print(f"File 2: {file2_path}")
    print()
    
    # Check if files exist
    if not os.path.exists(file1_path):
        print(f"ERROR: File 1 not found: {file1_path}")
        return
    if not os.path.exists(file2_path):
        print(f"ERROR: File 2 not found: {file2_path}")
        return
    
    try:
        # Run the comparison with debug output
        print("Running comparison with debug output...")
        print("=" * 50)
        
        # Enable debug output
        os.environ["DEBUG_VERBOSE"] = "true"
        
        # Run comparison
        results = compare_boms(file1_path, file2_path)
        
        print("\n" + "=" * 50)
        print("COMPARISON RESULTS:")
        print(f"New parts (Category 2): {len(results['new_parts'])}")
        print(f"Removed parts (Category 1): {len(results['removed_parts'])}")
        print(f"Modified parts (Category 3): {len(results['modified_parts'])}")
        print(f"Unchanged parts: {len(results['unchanged_parts'])}")
        
        # Show some examples of new parts
        if results['new_parts']:
            print("\nExamples of new parts (Category 2):")
            for i, part in enumerate(results['new_parts'][:5]):  # Show first 5
                print(f"  {i+1}. MPN: {part['MPN']}, Ref Des: {part['Ref Des/LOC']}, Qty: {part['Qty']}")
        
        # Show some examples of removed parts
        if results['removed_parts']:
            print("\nExamples of removed parts (Category 1):")
            for i, part in enumerate(results['removed_parts'][:5]):  # Show first 5
                print(f"  {i+1}. MPN: {part['MPN']}, Ref Des: {part['Ref Des/LOC']}, Qty: {part['Qty']}")
        
    except Exception as e:
        print(f"ERROR during comparison: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_mpn_normalization()
