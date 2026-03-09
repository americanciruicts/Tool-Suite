#!/usr/bin/env python3
"""
Detailed analysis of MPN values in both files
"""

import pandas as pd
import os

def analyze_mpns():
    """Analyze MPN values in both files"""
    
    file1_path = "test_files/motherboard BOM.xls"
    file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
    
    print("=== DETAILED MPN ANALYSIS ===")
    
    # Read File 1
    print(f"\nFile 1: {file1_path}")
    try:
        df1 = pd.read_excel(file1_path)
        print(f"Shape: {df1.shape}")
        print(f"Columns: {list(df1.columns)}")
        
        # Look for MPN column
        mpn_col1 = None
        for col in df1.columns:
            if 'manufacturer part number' in str(col).lower():
                mpn_col1 = col
                break
        
        if mpn_col1:
            print(f"\nMPN Column: {mpn_col1}")
            mpn_values1 = df1[mpn_col1].dropna().tolist()
            print(f"Total MPNs: {len(mpn_values1)}")
            print("First 20 MPNs:")
            for i, mpn in enumerate(mpn_values1[:20]):
                print(f"  {i+1:2d}. {mpn}")
            if len(mpn_values1) > 20:
                print(f"  ... and {len(mpn_values1) - 20} more")
        else:
            print("No MPN column found!")
            
    except Exception as e:
        print(f"Error reading File 1: {e}")
    
    # Read File 2
    print(f"\nFile 2: {file2_path}")
    try:
        df2 = pd.read_excel(file2_path)
        print(f"Shape: {df2.shape}")
        print(f"Columns: {list(df2.columns)}")
        
        # Look for MPN column
        mpn_col2 = None
        for col in df2.columns:
            if 'manufacturer part number' in str(col).lower():
                mpn_col2 = col
                break
        
        if mpn_col2:
            print(f"\nMPN Column: {mpn_col2}")
            mpn_values2 = df2[mpn_col2].dropna().tolist()
            print(f"Total MPNs: {len(mpn_values2)}")
            print("First 20 MPNs:")
            for i, mpn in enumerate(mpn_values2[:20]):
                print(f"  {i+1:2d}. {mpn}")
            if len(mpn_values2) > 20:
                print(f"  ... and {len(mpn_values2) - 20} more")
        else:
            print("No MPN column found!")
            
    except Exception as e:
        print(f"Error reading File 2: {e}")
    
    # Now let's compare the MPNs directly
    if 'mpn_col1' in locals() and 'mpn_col2' in locals() and mpn_col1 and mpn_col2:
        print("\n=== DIRECT MPN COMPARISON ===")
        
        # Get unique MPNs from both files
        unique_mpns1 = set(str(mpn).strip() for mpn in df1[mpn_col1].dropna() if str(mpn).strip())
        unique_mpns2 = set(str(mpn).strip() for mpn in df2[mpn_col2].dropna() if str(mpn).strip())
        
        print(f"File 1 unique MPNs: {len(unique_mpns1)}")
        print(f"File 2 unique MPNs: {len(unique_mpns2)}")
        
        # Find differences
        only_in_file1 = unique_mpns1 - unique_mpns2
        only_in_file2 = unique_mpns2 - unique_mpns1
        common = unique_mpns1 & unique_mpns2
        
        print(f"\nOnly in File 1 (removed): {len(only_in_file1)}")
        if only_in_file1:
            for i, mpn in enumerate(list(only_in_file1)[:10]):
                print(f"  {i+1:2d}. {mpn}")
            if len(only_in_file1) > 10:
                print(f"  ... and {len(only_in_file1) - 10} more")
        
        print(f"\nOnly in File 2 (new): {len(only_in_file2)}")
        if only_in_file2:
            for i, mpn in enumerate(list(only_in_file2)[:10]):
                print(f"  {i+1:2d}. {mpn}")
            if len(only_in_file2) > 10:
                print(f"  ... and {len(only_in_file2) - 10} more")
        
        print(f"\nCommon MPNs: {len(common)}")
        if common:
            for i, mpn in enumerate(list(common)[:10]):
                print(f"  {i+1:2d}. {mpn}")
            if len(common) > 10:
                print(f"  ... and {len(common) - 10} more")

if __name__ == "__main__":
    analyze_mpns()
