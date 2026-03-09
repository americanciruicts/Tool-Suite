#!/usr/bin/env python3
"""
Test the updated comparison logic
"""

import sys
import os

# Add the api directory to the path
sys.path.append('api')
from excel_tool import compare_boms

def test_updated_comparison():
    """Test the updated comparison logic"""
    
    file1_path = "test_files/motherboard BOM.xls"
    file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
    
    print("=== TESTING UPDATED COMPARISON LOGIC ===")
    print(f"File 1: {file1_path}")
    print(f"File 2: {file2_path}")
    print()
    
    try:
        # Run the comparison
        results = compare_boms(file1_path, file2_path)
        
        print("=== COMPARISON RESULTS ===")
        print(f"New parts (File 2 only): {len(results['new_parts'])}")
        print(f"Removed parts (File 1 only): {len(results['removed_parts'])}")
        print(f"Modified parts: {len(results['modified_parts'])}")
        print(f"Unchanged parts: {len(results['unchanged_parts'])}")
        
        print(f"\n=== REMOVED PARTS (should show 4 additions) ===")
        for part in results['removed_parts']:
            print(f"  - {part['MPN']} (Qty: {part['Qty']}, Line: {part['Line Number']})")
        
        print(f"\n=== NEW PARTS (should show 0) ===")
        for part in results['new_parts']:
            print(f"  - {part['MPN']} (Qty: {part['Qty']}, Line: {part['Line Number']})")
        
        print(f"\n=== MODIFIED PARTS ===")
        for part in results['modified_parts']:
            print(f"  - {part['MPN']} (Qty: {part['Qty']}, Line: {part['Line Number']})")
        
    except Exception as e:
        print(f"Error during comparison: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_updated_comparison()
