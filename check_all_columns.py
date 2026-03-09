#!/usr/bin/env python3
"""
Check all columns in both files to find MPN-like data
"""

import pandas as pd
import os

def check_all_columns():
    """Check all columns in both files"""
    
    file1_path = "test_files/motherboard BOM.xls"
    file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
    
    print("=== CHECKING ALL COLUMNS ===")
    
    # Read File 1
    print(f"\nFile 1: {file1_path}")
    try:
        df1 = pd.read_excel(file1_path)
        print(f"Shape: {df1.shape}")
        print(f"All columns:")
        for i, col in enumerate(df1.columns):
            print(f"  {i:2d}. '{col}'")
            
        # Check each column for potential MPN data
        print(f"\nAnalyzing each column for MPN-like data:")
        for i, col in enumerate(df1.columns):
            sample_values = df1[col].dropna().head(5).tolist()
            print(f"\n  Column {i}: '{col}'")
            print(f"    Sample values: {sample_values}")
            
            # Check if this looks like MPN data
            mpn_like = False
            for val in sample_values:
                val_str = str(val).strip()
                if (len(val_str) > 3 and 
                    any(char.isupper() for char in val_str) and
                    any(char.isdigit() for char in val_str)):
                    mpn_like = True
                    break
            
            if mpn_like:
                print(f"    *** POTENTIAL MPN COLUMN ***")
                
    except Exception as e:
        print(f"Error reading File 1: {e}")
    
    # Read File 2
    print(f"\nFile 2: {file2_path}")
    try:
        df2 = pd.read_excel(file2_path)
        print(f"Shape: {df2.shape}")
        print(f"All columns:")
        for i, col in enumerate(df2.columns):
            print(f"  {i:2d}. '{col}'")
            
        # Check each column for potential MPN data
        print(f"\nAnalyzing each column for MPN-like data:")
        for i, col in enumerate(df2.columns):
            sample_values = df2[col].dropna().head(5).tolist()
            print(f"\n  Column {i}: '{col}'")
            print(f"    Sample values: {sample_values}")
            
            # Check if this looks like MPN data
            mpn_like = False
            for val in sample_values:
                val_str = str(val).strip()
                if (len(val_str) > 3 and 
                    any(char.isupper() for char in val_str) and
                    any(char.isdigit() for char in val_str)):
                    mpn_like = True
                    break
            
            if mpn_like:
                print(f"    *** POTENTIAL MPN COLUMN ***")
                
    except Exception as e:
        print(f"Error reading File 2: {e}")

if __name__ == "__main__":
    check_all_columns()
