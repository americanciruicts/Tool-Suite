#!/usr/bin/env python3
"""
Debug script to examine raw data from both files
"""

import pandas as pd
import os

def debug_raw_data():
    """Examine raw data from both files"""
    
    file1_path = "test_files/motherboard BOM.xls"
    file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
    
    print("=== Raw Data Debug ===")
    
    # Read File 1
    print(f"\nFile 1: {file1_path}")
    try:
        df1 = pd.read_excel(file1_path)
        print(f"Shape: {df1.shape}")
        print(f"Columns: {list(df1.columns)}")
        print("\nFirst 10 rows:")
        print(df1.head(10))
        
        # Look for potential MPN columns
        print("\nPotential MPN columns (containing 'part', 'mpn', 'component'):")
        for col in df1.columns:
            col_lower = str(col).lower()
            if any(keyword in col_lower for keyword in ['part', 'mpn', 'component', 'item']):
                print(f"  {col}: {df1[col].head(5).tolist()}")
                
    except Exception as e:
        print(f"Error reading File 1: {e}")
    
    # Read File 2
    print(f"\nFile 2: {file2_path}")
    try:
        df2 = pd.read_excel(file2_path)
        print(f"Shape: {df2.shape}")
        print(f"Columns: {list(df2.columns)}")
        print("\nFirst 10 rows:")
        print(df2.head(10))
        
        # Look for potential MPN columns
        print("\nPotential MPN columns (containing 'part', 'mpn', 'component'):")
        for col in df2.columns:
            col_lower = str(col).lower()
            if any(keyword in col_lower for keyword in ['part', 'mpn', 'component', 'item']):
                print(f"  {col}: {df2[col].head(5).tolist()}")
                
    except Exception as e:
        print(f"Error reading File 2: {e}")

if __name__ == "__main__":
    debug_raw_data()
