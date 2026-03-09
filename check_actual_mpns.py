#!/usr/bin/env python3
"""
Check the actual MPN values in both files
"""

import pandas as pd
import os

def check_actual_mpns():
    """Check the actual MPN values in both files"""
    
    file1_path = "test_files/motherboard BOM.xls"
    file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
    
    print("=== CHECKING ACTUAL MPN VALUES ===")
    
    # Read File 1
    print(f"\nFile 1: {file1_path}")
    try:
        df1 = pd.read_excel(file1_path)
        mpn_values1 = df1['Manufacturer Part Number 1'].dropna().tolist()
        print(f"Total MPN values: {len(mpn_values1)}")
        print("All MPN values:")
        for i, val in enumerate(mpn_values1):
            print(f"  {i+1:2d}. {val}")
            
    except Exception as e:
        print(f"Error reading File 1: {e}")
    
    # Read File 2
    print(f"\nFile 2: {file2_path}")
    try:
        df2 = pd.read_excel(file2_path)
        mpn_values2 = df2['Manufacturer Part Number 1'].dropna().tolist()
        print(f"Total MPN values: {len(mpn_values2)}")
        print("All MPN values:")
        for i, val in enumerate(mpn_values2):
            print(f"  {i+1:2d}. {val}")
            
    except Exception as e:
        print(f"Error reading File 2: {e}")
    
    # Compare MPN columns
    if 'mpn_values1' in locals() and 'mpn_values2' in locals():
        print(f"\n=== MPN COMPARISON ===")
        
        # Convert to sets for comparison
        set1 = set(str(val).strip() for val in mpn_values1 if str(val).strip())
        set2 = set(str(val).strip() for val in mpn_values2 if str(val).strip())
        
        print(f"File 1 unique MPNs: {len(set1)}")
        print(f"File 2 unique MPNs: {len(set2)}")
        
        # Find differences
        only_in_file1 = set1 - set2
        only_in_file2 = set2 - set1
        common = set1 & set2
        
        print(f"\nOnly in File 1 (removed): {len(only_in_file1)}")
        if only_in_file1:
            for val in sorted(only_in_file1):
                print(f"  - {val}")
        
        print(f"\nOnly in File 2 (new): {len(only_in_file2)}")
        if only_in_file2:
            for val in sorted(only_in_file2):
                print(f"  - {val}")
        
        print(f"\nCommon MPNs: {len(common)}")
        if common:
            for val in sorted(common)[:20]:  # Show first 20
                print(f"  - {val}")
            if len(common) > 20:
                print(f"  ... and {len(common) - 20} more")

if __name__ == "__main__":
    check_actual_mpns()
