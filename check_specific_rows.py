#!/usr/bin/env python3
"""
Check the specific rows that contain the 4 additions
"""

import pandas as pd
import os

def check_specific_rows():
    """Check the specific rows that contain the 4 additions"""
    
    file1_path = "test_files/motherboard BOM.xls"
    file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
    
    print("=== CHECKING SPECIFIC ROWS WITH 4 ADDITIONS ===")
    
    # Read File 1
    print(f"\nFile 1: {file1_path}")
    try:
        df1 = pd.read_excel(file1_path)
        print(f"Shape: {df1.shape}")
        
        # Look for the specific rows with the 4 additions
        print("\nLooking for rows with the 4 additions:")
        additions = ["Red Wire", "Black Wire", "DC Connector", "Connector Pins"]
        
        for addition in additions:
            # Check in Comment column
            comment_matches = df1[df1['Comment'] == addition]
            if not comment_matches.empty:
                print(f"\nFound '{addition}' in Comment column:")
                for idx, row in comment_matches.iterrows():
                    print(f"  Row {idx}: Comment='{row['Comment']}', MPN='{row['Manufacturer Part Number 1']}', RefDes='{row['Ref Designator']}', Qty='{row['Quantity']}'")
            else:
                print(f"\n'{addition}' NOT found in Comment column")
            
            # Check in other columns
            for col in df1.columns:
                if col != 'Comment':
                    matches = df1[df1[col] == addition]
                    if not matches.empty:
                        print(f"  Found '{addition}' in {col} column at row(s): {matches.index.tolist()}")
        
        # Check the last few rows specifically
        print(f"\nLast 10 rows of File 1:")
        print(df1.tail(10)[['Comment', 'Manufacturer Part Number 1', 'Ref Designator', 'Quantity']])
        
    except Exception as e:
        print(f"Error reading File 1: {e}")
    
    # Read File 2
    print(f"\nFile 2: {file2_path}")
    try:
        df2 = pd.read_excel(file2_path)
        print(f"Shape: {df2.shape}")
        
        # Check the last few rows specifically
        print(f"\nLast 10 rows of File 2:")
        print(df2.tail(10)[['Comment', 'Manufacturer Part Number 1', 'Designator', 'Quantity']])
        
    except Exception as e:
        print(f"Error reading File 2: {e}")

if __name__ == "__main__":
    check_specific_rows()
