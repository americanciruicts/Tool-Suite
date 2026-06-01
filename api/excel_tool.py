import pandas as pd
import re
import os
import sys
from functools import lru_cache
from typing import Optional, List, Tuple

from ai_helpers import (
    classify_column,
    score_column_content,
    normalize_quantity as _ai_normalize_quantity,
    normalize_mpn as _ai_normalize_mpn,
    find_fuzzy_mpn_match,
    description_similarity,
)

DEBUG_VERBOSE = os.getenv("DEBUG_VERBOSE", "false").lower() == "true"


def _read_excel_cached_key(file_path: str, header) -> tuple:
    """Cache key: path + mtime + size + header-arg. mtime+size invalidates when
    the underlying file changes (temp files on each request stay distinct)."""
    try:
        st = os.stat(file_path)
        return (file_path, st.st_mtime_ns, st.st_size, header)
    except OSError:
        return (file_path, 0, 0, header)


@lru_cache(maxsize=32)
def _cached_read_excel(cache_key: tuple):
    file_path, _mtime, _size, header = cache_key
    ext = os.path.splitext(file_path)[1].lower()
    engine = "xlrd" if ext == ".xls" else None
    # Convert back from the sentinel "NONE" we stored to the real `None` that
    # pandas expects for "no header".
    header_arg = None if header == "NONE" else header
    if engine:
        return pd.read_excel(file_path, header=header_arg, engine=engine)
    return pd.read_excel(file_path, header=header_arg)


def read_excel_cached(file_path: str, header=None):
    """Thin wrapper around pd.read_excel that caches results in-process so
    repeated reads of the same file+header within a request are ~free."""
    # Cache returns a shared DataFrame; callers that mutate should .copy().
    key_header = "NONE" if header is None else header
    cache_key = _read_excel_cached_key(file_path, key_header)
    return _cached_read_excel(cache_key)

def safe_print(text):
    """Safe printing function that handles Unicode characters on Windows."""
    if not DEBUG_VERBOSE:
        return
    try:
        print(text)
    except UnicodeEncodeError:
        safe_text = str(text).encode('ascii', 'replace').decode('ascii')
        print(safe_text)

# Column mapping keywords
HEADER_KEYWORDS = {
    'mpn': [
        # Core acronyms
        'mpn', 'pn', 'p/n', 'p#', 'pno',
        # Part number variations - with/without spaces, punctuation
        'part #', 'part#', 'part #.', 'part#.', 'part # ', ' part#', ' part #',
        'part no', 'part no.', 'part no ', ' part no', 'partno', 'part_no',
        'part number', 'part num', 'partnumber', 'part_number', 'part_num',
        'part-number', 'part-no', 'part-#', 'part - #', 'part - no',
        # Item variations
        'item no', 'item #', 'item#', 'item number', 'itemno', 'item_no', 'item_#',
        'component number', 'comp no', 'comp #', 'comp#', 'component #',
        # Manufacturer variations - all spacing combinations
        'manufacturer part number', 'manufacturer pn', 'manufacturer p/n', 'manufacturer p#',
        'manufacturer part no', 'manufacturer part #', 'manufacturer part#',
        'manufacturer 1 pn', 'manufacturer 1 p/n', 'manufacturer 1 part number', 'manufacturer 1 part no',
        'mfg part number', 'mfg pn', 'mfg p/n', 'mfg part no', 'mfg part #', 'mfg part#',
        'mfr part number', 'mfr pn', 'mfr p/n', 'mfr part no', 'mfr part #', 'mfr part#',
        'manufacturing part number', 'manufacturing pn', 'manufacturing p/n', 'manufacturing part no',
        # Vendor/Supplier variations
        'vendor part number', 'vendor pn', 'vendor p/n', 'vendor part #', 'vendor part#', 'vendor part no',
        'supplier part number', 'supplier pn', 'supplier p/n', 'supplier part no', 'supplier part #', 'supplier part#',
        # Stock/Catalog variations
        'stock number', 'stock no', 'stock #', 'stock#', 'stock no.', 'stock_no',
        'catalog number', 'catalog no', 'catalog #', 'catalog#', 'cat no', 'cat #', 'cat#',
        'catalogue number', 'catalogue no', 'catalogue #',
        # Model/Product variations
        'model number', 'model no', 'model #', 'model#', 'model no.', 'model_no',
        'product number', 'product no', 'product #', 'product#', 'prod no', 'prod #',
        # Material variations
        'material number', 'material no', 'material #', 'material#', 'material pn',
        'mat no', 'mat #', 'mat#', 'mat number', 'material_no',
        # SKU and other variations
        'sku', 'stock keeping unit', 'upc', 'barcode',
        # Generic terms that might be used
        'part', 'component', 'item', 'material', 'piece',
        'component part number', 'component pn', 'component p/n',
        'item part number', 'item pn', 'item p/n',
        # Common typos and variations
        'partnum', 'part_id', 'part id', 'part-id', 'partid',
        'component_id', 'comp_id', 'item_id',
        # International variations
        'teil nr', 'teil-nr', 'teilnummer', 'artikel nr', 'artikel-nr',
        'numero de parte', 'numero parte', 'ref', 'referencia'
    ],
    'refdes': [
        # Acronyms
        'refdes', 'ref des', 'ref', 'loc', 'designator',
        # Full names and variations
        'reference designator', 'reference des', 'reference designation',
        'location', 'loc', 'position', 'pos', 'placement',
        'refdes/loc', 'ref des/loc', 'reference/location', 'ref/loc',
        'ref. des.', 'ref. des', 'reference designator/location',
        'component location', 'component position', 'component placement',
        'part location', 'part position', 'part placement',
        'designation', 'designator', 'reference', 'ref designation'
    ],
    'qty': [
        # Acronyms
        'qty', 'qnty', "q'ty", 'qnt', 'qty.', 'qty req', 'qty required',
        # Full names and variations
        'quantity', 'quantities', 'qty required', 'required qty', 'required quantity',
        'amount', 'count', 'number', 'count required', 'amount required',
        'quantity needed', 'qty needed', 'quantity per', 'qty per',
        'quantity per assembly', 'qty per assembly', 'quantity per unit',
        'qty per unit', 'quantity per board', 'qty per board',
        'total quantity', 'total qty', 'sum quantity', 'sum qty',
        'quantity total', 'qty total', 'quantity count', 'qty count'
    ],
    'description': [
        # Acronyms
        'desc', 'description',
        # Full names and variations
        'part description', 'component description', 'item description',
        'notes', 'note', 'comment', 'comments', 'remarks', 'remark',
        'part name', 'component name', 'item name', 'part title',
        'component title', 'item title', 'part details', 'component details',
        'item details', 'part info', 'component info', 'item info',
        'part specification', 'component specification', 'item specification',
        'part spec', 'component spec', 'item spec', 'specification',
        'part summary', 'component summary', 'item summary',
        'part notes', 'component notes', 'item notes',
        'description text', 'desc text', 'part text', 'component text',
        # Additional variations
        'description text', 'desc text', 'part text', 'component text',
        'part description text', 'component description text',
        'item description text', 'part details text',
        'component details text', 'item details text',
        'part info text', 'component info text', 'item info text',
        'part specification text', 'component specification text',
        'item specification text', 'part spec text', 'component spec text',
        'item spec text', 'specification text', 'part summary text',
        'component summary text', 'item summary text', 'part notes text',
        'component notes text', 'item notes text',
        # More specific keywords
        'component', 'part', 'item', 'material', 'materials',
        'component description', 'part description', 'item description',
        'material description', 'component name', 'part name', 'item name',
        'material name', 'component type', 'part type', 'item type',
        'material type', 'component info', 'part info', 'item info',
        'material info', 'component details', 'part details', 'item details',
        'material details', 'component notes', 'part notes', 'item notes',
        'material notes', 'component specification', 'part specification',
        'item specification', 'material specification', 'component spec',
        'part spec', 'item spec', 'material spec', 'component summary',
        'part summary', 'item summary', 'material summary'
    ]
}

def find_header_row_and_map(file_path):
    """Find the header row and map columns to standard names."""
    safe_print(f"\nFinding headers for: {os.path.basename(file_path)}")
    
    # Read the file without headers first (cached)
    ext = os.path.splitext(file_path)[1].lower()
    df_raw = read_excel_cached(file_path, header=None)

    safe_print(f"Raw file shape: {df_raw.shape}")
    
    # Debug: Show first 15 rows to understand the file structure
    safe_print(f"\nFirst 15 rows for debugging:")
    for i in range(min(15, len(df_raw))):
        row_data = df_raw.iloc[i].tolist()
        # Show only first 10 columns to avoid overwhelming output
        row_display = row_data[:10] if len(row_data) > 10 else row_data
        safe_print(f"Row {i}: {row_display}")
    
    # Look for the header row by checking each row
    header_row = None
    best_header_score = 0
    best_header_row = 0
    
    for row_idx in range(min(30, len(df_raw))):  # Check first 30 rows
        row = df_raw.iloc[row_idx]
        header_like_count = 0
        header_score = 0
        
        for cell in row:
            if pd.notna(cell) and isinstance(cell, str):
                cell_lower = str(cell).lower().strip()
                # Check for header-like keywords with different weights
                if any(kw in cell_lower for kw in ['mpn', 'part', 'qty', 'desc', 'ref', 'loc', 'item', 'mfr', 'package', 'manufacturer', 'designator', 'quantity']):
                    header_like_count += 1
                    # Give higher weight to specific MPN-related keywords
                    if any(kw in cell_lower for kw in ['manufacturer', 'mpn', 'part number', 'pn']):
                        header_score += 3
                    elif any(kw in cell_lower for kw in ['qty', 'quantity']):
                        header_score += 2
                    elif any(kw in cell_lower for kw in ['desc', 'description']):
                        header_score += 2
                    elif any(kw in cell_lower for kw in ['ref', 'designator']):
                        header_score += 2
                    else:
                        header_score += 1
        
        safe_print(f"Row {row_idx}: {list(row)} -> Header-like count: {header_like_count}, Score: {header_score}")
        
        # Use a more flexible scoring system
        if header_like_count >= 2 and header_score >= 4:  # Lower threshold but require good score
            header_row = row_idx
            safe_print(f"  -> FOUND HEADER ROW at index {row_idx} (score: {header_score})")
            break
        elif header_score > best_header_score:
            best_header_score = header_score
            best_header_row = row_idx
    
    if header_row is None:
        if best_header_score >= 2:  # Use best candidate if we found something reasonable
            header_row = best_header_row
            safe_print(f"  -> USING BEST CANDIDATE HEADER ROW at index {header_row} (score: {best_header_score})")
        else:
            safe_print("WARNING: No header row found, using row 0")
            header_row = 0 
    
    # Now read the file with the correct header row (cached)
    df = read_excel_cached(file_path, header=header_row)

    safe_print(f"Columns after header detection: {list(df.columns)}")
    
    # Debug: Show all column names with their indices
    safe_print(f"\nDetailed column analysis:")
    for idx, col_name in enumerate(df.columns):
        col_lower = str(col_name).lower().strip()
        safe_print(f"  Column {idx}: '{col_name}' (lowercase: '{col_lower}')")
    
    # Map columns to standard names
    col_map = {}
    
    # MPN detection with priority
    mpn_candidates = []
    for idx, col_name in enumerate(df.columns):
        # Handle the column name more carefully - strip all whitespace
        cell_lower = str(col_name).lower().strip()
        cell_original = str(col_name).strip()  # Keep original case for debugging

        safe_print(f"  Checking column {idx}: '{col_name}' -> normalized: '{cell_lower}'")
        
        # Skip very long descriptions that might contain part-related words
        if len(cell_lower) > 50:  # Skip very long descriptions
            continue
            
        # Priority 1: Exact "MPN" and exact matches for our problem files
        if cell_lower == 'mpn':
            mpn_candidates.append((idx, 10, 'Exact MPN'))
        elif cell_lower == 'part#':  # Exact match for "Part#" (with stripped whitespace)
            mpn_candidates.append((idx, 10, 'Exact Part#'))
        elif cell_lower == 'mfg p/n':  # Exact match for "Mfg P/N"
            mpn_candidates.append((idx, 10, 'Exact Mfg P/N'))
        # Priority 2: Manufacturer Part Number variations
        elif 'manufacturer part' in cell_lower and ('no' in cell_lower or 'number' in cell_lower):
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'manufacturer p/n' in cell_lower or 'manufacturer pn' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'manufacturer 1 pn' in cell_lower or 'manufacturer 1 p/n' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'manufacturer 1' in cell_lower and 'pn' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'mfg p/n' in cell_lower or 'mfg pn' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'mfg. p/n' in cell_lower or 'mfg. pn' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        # Handle exact "Mfg P/N" case (case insensitive)
        elif cell_lower == 'mfg p/n' or cell_lower == 'mfg.p/n' or cell_lower == 'mfg. p/n':
            mpn_candidates.append((idx, 9, 'Mfg P/N Exact Match'))
        elif 'manufacturer part no' in cell_lower or 'manufacturer part number' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'mfg part no' in cell_lower or 'mfg part number' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'manufacturer part#' in cell_lower or 'mfg part#' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'manufacturer part no.' in cell_lower or 'mfg part no.' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        elif 'manufacturer part number' in cell_lower or 'mfg part number' in cell_lower:
            mpn_candidates.append((idx, 8, 'Manufacturer Part Number'))
        # Priority 3: Vendor Part Number variations  
        elif 'vendor part' in cell_lower and ('no' in cell_lower or 'number' in cell_lower):
            mpn_candidates.append((idx, 6, 'Vendor Part Number'))
        elif 'vendor p/n' in cell_lower or 'vendor pn' in cell_lower:
            mpn_candidates.append((idx, 6, 'Vendor Part Number'))
        elif 'vendor part no' in cell_lower or 'vendor part number' in cell_lower:
            mpn_candidates.append((idx, 6, 'Vendor Part Number'))
        # Priority 4: Other part number variations - more flexible matching
        elif len(cell_lower) <= 30 and any(kw in cell_lower for kw in [
            'part number', 'part no', 'part #', 'part#', 'part num', 'partno', 'partnumber',
            'pn', 'p/n', 'p#', 'item#', 'item #', 'item no', 'item number',
            'comp #', 'comp#', 'component #', 'component number',
            'material #', 'material#', 'material no', 'material number',
            'stock #', 'stock#', 'stock no', 'catalog #', 'catalog#', 'catalog no'
        ]):
            mpn_candidates.append((idx, 4, 'Other Part Number'))
    
    # Select the highest priority MPN column
    if mpn_candidates:
        mpn_candidates.sort(key=lambda x: x[1], reverse=True)
        selected_mpn = mpn_candidates[0]
        col_map['mpn'] = selected_mpn[0]
        safe_print(f"Selected MPN column: {df.columns[selected_mpn[0]]} ({selected_mpn[2]})")
    else:
        safe_print("WARNING: No MPN column found using primary patterns!")
        safe_print("Trying fallback detection...")

        # Fallback: Look for ANY column that might contain part numbers
        for idx, col_name in enumerate(df.columns):
            cell_lower = str(col_name).lower().strip()
            safe_print(f"  Checking fallback column: '{col_name}' -> '{cell_lower}'")

            # Very aggressive pattern matching
            if (
                ('part' in cell_lower and ('#' in cell_lower or 'no' in cell_lower or 'num' in cell_lower)) or
                ('item' in cell_lower and ('#' in cell_lower or 'no' in cell_lower or 'num' in cell_lower)) or
                ('mfg' in cell_lower and ('p' in cell_lower or 'n' in cell_lower)) or
                ('manufacturer' in cell_lower and ('p' in cell_lower or 'n' in cell_lower)) or
                (cell_lower in ['pn', 'p/n', 'mpn', 'part', 'item', 'component']) or
                ('component' in cell_lower and ('#' in cell_lower or 'no' in cell_lower or 'num' in cell_lower))
            ):
                safe_print(f"  -> FALLBACK MATCH: Using '{col_name}' as MPN column")
                col_map['mpn'] = idx
                break
        else:
            safe_print("WARNING: No MPN column found even with fallback detection!")
    
    # Quantity detection
    qty_candidates = []
    for idx, col_name in enumerate(df.columns):
        cell_lower = str(col_name).lower().strip()
        if any(kw in cell_lower for kw in ['qty', 'quantity', 'qty.', 'qty:']):
            qty_candidates.append((idx, cell_lower))
    
    if qty_candidates:
        col_map['qty'] = qty_candidates[0][0]
        safe_print(f"Selected Qty column: {df.columns[qty_candidates[0][0]]}")
    else:
        safe_print("WARNING: No Qty column found!")
    
    # Ref Des/LOC detection
    refdes_candidates = []
    for idx, col_name in enumerate(df.columns):
        cell_lower = str(col_name).lower().strip()
        if any(kw in cell_lower for kw in ['ref', 'reference', 'designator', 'designation', 'loc', 'location']):
            refdes_candidates.append((idx, cell_lower))
    
    if refdes_candidates:
        col_map['refdes'] = refdes_candidates[0][0]
        safe_print(f"Selected Ref Des/LOC column: {df.columns[refdes_candidates[0][0]]}")
    else:
        safe_print("WARNING: No Ref Des/LOC column found!")
    
    # Description detection
    desc_candidates = []
    for idx, col_name in enumerate(df.columns):
        cell_lower = str(col_name).lower().strip()
        if any(kw in cell_lower for kw in ['desc', 'description', 'note', 'comment', 'remark']):
            desc_candidates.append((idx, cell_lower))
    
    if desc_candidates:
        col_map['description'] = desc_candidates[0][0]
        safe_print(f"Selected Description column: {df.columns[desc_candidates[0][0]]}")
    else:
        safe_print("WARNING: No Description column found!")
    
    safe_print(f"Final column map: {col_map}")
    return header_row, col_map

def read_bom_with_auto_headers(file_path):
    """Read BOM file with auto-detected headers."""
    safe_print(f"Reading: {file_path}")
    
    header_row, col_map = find_header_row_and_map(file_path)
    ext = os.path.splitext(file_path)[1].lower()

    # First, read without headers to get the actual data (cached)
    df_raw = read_excel_cached(file_path, header=None)

    # Get the MPN column data before pandas converts it
    if 'mpn' in col_map and col_map['mpn'] < len(df_raw.columns):
        mpn_col_idx = col_map['mpn']
        # Get the original MPN values as strings
        original_mpn_values = df_raw.iloc[header_row+1:, mpn_col_idx].astype(str).tolist()
        safe_print(f"Original MPN values (first 5): {original_mpn_values[:5]}")

    # Now read with headers (cached; callers mutate columns so copy)
    df = read_excel_cached(file_path, header=header_row).copy()
    
    # Convert MPN column to string to preserve original formatting
    if 'mpn' in col_map and col_map['mpn'] < len(df.columns):
        mpn_col = df.columns[col_map['mpn']]
        df[mpn_col] = df[mpn_col].astype(str)
        safe_print(f"Converted MPN column '{mpn_col}' to string type")
        
        # Replace with original values if we have them
        if 'original_mpn_values' in locals() and len(original_mpn_values) == len(df):
            df[mpn_col] = original_mpn_values
            safe_print(f"Restored original MPN values")
    
    safe_print(f"Detected columns: {col_map}")
    safe_print(f"Available columns: {list(df.columns)}")
    safe_print(f"Header row: {header_row}")
    safe_print(f"Header row content: {df.iloc[header_row].tolist()}")
    safe_print(f"Column mapping details:")
    for key, idx in col_map.items():
        if idx < len(df.columns):
            safe_print(f"  {key} -> {df.columns[idx]} (index {idx})")
        else:
            safe_print(f"  {key} -> INVALID INDEX {idx}")
    
    # Additional debugging: Show all columns and their sample values
    safe_print(f"\nAll columns with sample values:")
    for idx, col_name in enumerate(df.columns):
        sample_values = df[col_name].dropna().head(3).tolist()
        safe_print(f"  Column {idx}: '{col_name}' -> Sample values: {sample_values}")
    
    # Check if description column was found and has data
    if 'description' in col_map:
        desc_col_idx = col_map['description']
        if desc_col_idx < len(df.columns):
            desc_col_name = df.columns[desc_col_idx]
            desc_sample_values = df[desc_col_name].dropna().head(5).tolist()
            safe_print(f"\nDescription column '{desc_col_name}' (index {desc_col_idx}) sample values:")
            safe_print(f"  {desc_sample_values}")
            safe_print(f"  Total non-null values: {len(df[desc_col_name].dropna())}")
            
            # Validate that the description column has meaningful data
            non_null_count = len(df[desc_col_name].dropna())
            if non_null_count == 0:
                safe_print(f"  WARNING: Description column '{desc_col_name}' has no data!")
                # Remove this column from the map and try to find another
                del col_map['description']
            elif non_null_count < 3:
                safe_print(f"  WARNING: Description column '{desc_col_name}' has very little data ({non_null_count} values)")
                # Check if the values are meaningful
                meaningful_values = [v for v in desc_sample_values if str(v).strip() and str(v).lower() not in ['nan', 'n/a', 'none', '']]
                if len(meaningful_values) == 0:
                    safe_print(f"  WARNING: No meaningful values found in description column!")
                    del col_map['description']
        else:
            safe_print(f"\nWARNING: Description column index {desc_col_idx} is invalid!")
            del col_map['description']
    else:
        safe_print(f"\nWARNING: No description column found!")
        safe_print(f"Available columns: {list(df.columns)}")
        # Try to find a description-like column
        for idx, col_name in enumerate(df.columns):
            col_lower = str(col_name).lower()
            if any(kw in col_lower for kw in ['desc', 'note', 'comment', 'remark', 'component', 'part', 'item', 'material']):
                safe_print(f"  Potential description column: '{col_name}' (index {idx})")
                sample_values = df[col_name].dropna().head(3).tolist()
                safe_print(f"    Sample values: {sample_values}")
                # Check if this column has meaningful data
                meaningful_values = [v for v in sample_values if str(v).strip() and str(v).lower() not in ['nan', 'n/a', 'none', '']]
                if len(meaningful_values) > 0:
                    safe_print(f"    Found meaningful values: {meaningful_values}")
                    col_map['description'] = idx
                    break
    
    # Map columns to standard names
    mapped_cols = {}
    for key, idx in col_map.items():
        if idx < len(df.columns):
            mapped_cols[key] = df.columns[idx]
    
    return df, mapped_cols

def compare_boms(file1, file2, fuzzy_threshold: float = 0.88, ignore_pairs: Optional[List[Tuple[str, str]]] = None):
    """Compare two BOM files and return differences.

    Args:
        file1, file2: paths to the two Excel files
        fuzzy_threshold: 0..1 — minimum similarity for the fuzzy MPN-rename
            pass to flag a removed+added pair as the same physical part.
        ignore_pairs: optional list of (mpn_in_file_1, mpn_in_file_2) pairs
            the user has manually rejected. Those pairs will not be promoted
            to "MPN renamed" even if their similarity passes the threshold.
    """
    safe_print("Starting BOM comparison...")

    # Read both files
    df1, map1 = read_bom_with_auto_headers(file1)
    df2, map2 = read_bom_with_auto_headers(file2)
    
    # Check for required MPN column with detailed error reporting
    missing_mpn_files = []
    if 'mpn' not in map1:
        missing_mpn_files.append(f"File 1 - Available columns: {list(df1.columns)}")
    if 'mpn' not in map2:
        missing_mpn_files.append(f"File 2 - Available columns: {list(df2.columns)}")

    if missing_mpn_files:
        error_msg = "MPN column not detected in:\n" + "\n".join(missing_mpn_files)
        error_msg += "\n\nSupported MPN column patterns include: 'MPN', 'Part#', 'Part #', 'Part Number', 'Mfg P/N', 'P/N', etc."
        raise ValueError(error_msg)
    
    # Normalize values
    def norm(val):
        """Normalize values while preserving original MPN formatting."""
        if pd.isna(val) or val == '' or str(val).lower() in ['nan', 'none', 'null', '']:
            return ''
        
        # Convert to string and strip whitespace
        val_str = str(val).strip()
        
        # Skip empty strings after stripping
        if not val_str or val_str.lower() in ['nan', 'none', 'null']:
            return ''
        
        # For MPN values, preserve original case and formatting
        # Only convert to uppercase for comparison purposes
        normalized = val_str.upper()
        
        # Handle common electronic component value variations
        # Normalize resistance values: "750R" should match "750"
        if normalized.endswith('R') and len(normalized) > 1:
            # Check if everything before 'R' is a number (including decimals)
            try:
                float(normalized[:-1])
                # If it's a valid number followed by R, treat it as equivalent to just the number
                normalized = normalized[:-1]
            except ValueError:
                # Not a numeric value followed by R, keep as is
                pass
        
        return normalized
    
    # Create comparison keys
    mpn_col1 = df1.columns[map1['mpn']] if isinstance(map1['mpn'], int) else map1['mpn']
    mpn_col2 = df2.columns[map2['mpn']] if isinstance(map2['mpn'], int) else map2['mpn']
    
    # Use MPN for comparison, but fall back to Comment if MPN is empty
    def generate_key(row, df, mpn_col):
        mpn_val = row[mpn_col]
        comment_val = row.get('Comment', '') if 'Comment' in df.columns else ''
        
        # If MPN exists and is valid, use it
        if not pd.isna(mpn_val) and str(mpn_val).strip() not in ['', 'nan', 'none', 'null']:
            return norm(mpn_val)
        
        # If MPN is empty but Comment exists, use Comment as the key
        if not pd.isna(comment_val) and str(comment_val).strip() not in ['', 'nan', 'none', 'null']:
            return f"COMMENT_{norm(comment_val)}"
        
        # If neither exists, return empty
        return ''
    
    # Generate keys for each row
    key1 = df1.apply(lambda row: generate_key(row, df1, mpn_col1), axis=1)
    key2 = df2.apply(lambda row: generate_key(row, df2, mpn_col2), axis=1)
    
    # Debug: Show some key examples
    safe_print("DEBUG: Key generation examples:")
    safe_print(f"File 1 keys (first 10): {key1.head(10).tolist()}")
    safe_print(f"File 2 keys (first 10): {key2.head(10).tolist()}")
    
    # Debug: Show keys for the last 10 rows (where the 4 additions are)
    safe_print(f"File 1 keys (last 10): {key1.tail(10).tolist()}")
    safe_print(f"File 2 keys (last 10): {key2.tail(10).tolist()}")
    
    # Debug: Log the MPN normalization process
    safe_print("DEBUG: MPN normalization process:")
    safe_print(f"File 1 MPNs (first 10): {df1[mpn_col1].head(10).tolist()}")
    safe_print(f"File 1 normalized keys (first 10): {key1.head(10).tolist()}")
    safe_print(f"File 2 MPNs (first 10): {df2[mpn_col2].head(10).tolist()}")
    safe_print(f"File 2 normalized keys (first 10): {key2.head(10).tolist()}")
    
    # Debug: Show specific MPN examples that might be problematic
    safe_print("DEBUG: Specific MPN examples:")
    for i, (orig, norm_val) in enumerate(zip(df1[mpn_col1].head(10), key1.head(10))):
        safe_print(f"  File1 Row {i}: '{orig}' -> '{norm_val}'")
    for i, (orig, norm_val) in enumerate(zip(df2[mpn_col2].head(10), key2.head(10))):
        safe_print(f"  File2 Row {i}: '{orig}' -> '{norm_val}'")
    
    # Filter out empty/nan keys but keep original indices
    # Create masks for valid entries - include rows with MPN OR Comment
    def has_valid_data(row, df, mpn_col):
        mpn_val = row[mpn_col]
        comment_val = row.get('Comment', '') if 'Comment' in df.columns else ''
        
        # Include row if it has either a valid MPN OR a meaningful comment
        has_mpn = not pd.isna(mpn_val) and str(mpn_val).strip() not in ['', 'nan', 'none', 'null']
        has_comment = not pd.isna(comment_val) and str(comment_val).strip() not in ['', 'nan', 'none', 'null']
        
        return has_mpn or has_comment
    
    # Apply filtering that includes rows with either MPN or Comment
    mask1 = df1.apply(lambda row: has_valid_data(row, df1, mpn_col1), axis=1)
    mask2 = df2.apply(lambda row: has_valid_data(row, df2, mpn_col2), axis=1)
    
    # Debug: Log filtering process
    safe_print("DEBUG: Filtering process:")
    safe_print(f"File 1 total rows: {len(df1)}")
    safe_print(f"File 1 valid rows (MPN or Comment): {mask1.sum()}")
    safe_print(f"File 1 filtered rows: {len(df1[mask1])}")
    safe_print(f"File 2 total rows: {len(df2)}")
    safe_print(f"File 2 valid rows (MPN or Comment): {mask2.sum()}")
    safe_print(f"File 2 filtered rows: {len(df2[mask2])}")
    
    # Filter dataframes to only include rows with valid data
    df1_filtered = df1[mask1].copy()
    df2_filtered = df2[mask2].copy()
    
    # Build sets of MPNs — O(N)
    set1 = set(key1)
    set2 = set(key2)
    
    # Debug: Log the comparison sets
    safe_print("DEBUG: Comparison sets:")
    safe_print(f"File 1 unique MPNs: {len(set1)} items")
    safe_print(f"File 2 unique MPNs: {len(set2)} items")
    safe_print(f"New parts (File 2 only): {len(set2 - set1)} items")
    safe_print(f"Removed parts (File 1 only): {len(set1 - set2)} items")
    safe_print(f"Common parts (both files): {len(set1 & set2)} items")

    # Use original data for comparison (not filtered)
    # The filtering is already handled by the key generation

    # O(1) column name resolution
    def _mapped_col(df, column_map, key):
        if key not in column_map:
            return None
        col = column_map[key]
        return df.columns[col] if isinstance(col, int) else col

    # Build O(1) lookup: normalized key -> first row index
    row1_by_key = {}
    for idx, k in key1.items():
        if k and k not in row1_by_key:
            row1_by_key[k] = idx
    row2_by_key = {}
    for idx, k in key2.items():
        if k and k not in row2_by_key:
            row2_by_key[k] = idx
    
    # Debug: Show what keys we have
    safe_print("DEBUG: Keys in row1_by_key:")
    for k, idx in row1_by_key.items():
        safe_print(f"  '{k}' -> row {idx}")
    
    safe_print("DEBUG: Keys in row2_by_key:")
    for k, idx in row2_by_key.items():
        safe_print(f"  '{k}' -> row {idx}")
    
    # Debug: Show what keys are in set1 - set2 (removed parts)
    removed_keys = set1 - set2
    safe_print(f"DEBUG: Removed keys (set1 - set2): {removed_keys}")
    
    # Debug: Show which of these keys are found in row1_by_key
    for k in removed_keys:
        if k in row1_by_key:
            safe_print(f"  '{k}' -> FOUND in row1_by_key at row {row1_by_key[k]}")
        else:
            safe_print(f"  '{k}' -> NOT FOUND in row1_by_key")

    # O(1) getters by row index
    def _get_value_by_index(df, row_index, column_map, column_name):
        col = _mapped_col(df, column_map, column_name)
        if col is None or row_index not in df.index:
            return 'N/A'
        return df.at[row_index, col]

    def _get_mpn_by_index(df, row_index, column_map):
        val = _get_value_by_index(df, row_index, column_map, 'mpn')
        if pd.isna(val):
            # Try to get Comment as fallback
            comment_val = _get_value_by_index(df, row_index, column_map, 'comment')
            if not pd.isna(comment_val) and str(comment_val).strip() not in ['', 'nan', 'none', 'null']:
                return str(comment_val).strip()
            return 'N/A'
        if isinstance(val, (int, float)) and not pd.isna(val) and val == int(val):
            return str(int(val))
        return str(val).strip()
    
    def _get_mpn_by_index_with_comment_fallback(df, row_index, column_map, key):
        """Get MPN value by index, with special handling for COMMENT_ keys"""
        if key.startswith('COMMENT_'):
            # This is a comment-based key, get the comment value directly
            # First, try to find the comment column
            comment_col = None
            for col in df.columns:
                if 'comment' in str(col).lower():
                    comment_col = col
                    break
            
            if comment_col:
                comment_val = df.at[row_index, comment_col]
                
                if not pd.isna(comment_val) and str(comment_val).strip() not in ['', 'nan', 'none', 'null']:
                    return str(comment_val).strip()
                else:
                    # Extract from key as fallback
                    return key[8:]  # Remove 'COMMENT_' prefix
            else:
                # No comment column found, extract from key
                return key[8:]  # Remove 'COMMENT_' prefix
        else:
            # Regular MPN key
            return _get_mpn_by_index(df, row_index, column_map)
    
    def _get_mpn_by_key(df, key, column_map):
        """Get MPN value by key, handling COMMENT_ prefixed keys"""
        if key.startswith('COMMENT_'):
            # This is a comment-based key, extract the comment value
            comment_val = key[8:]  # Remove 'COMMENT_' prefix
            # Find the row with this comment
            for idx, row in df.iterrows():
                comment_col = None
                for col in df.columns:
                    if 'comment' in str(col).lower():
                        comment_col = col
                        break
                if comment_col and str(row[comment_col]).strip().upper() == comment_val:
                    return str(row[comment_col]).strip()
            return comment_val  # Fallback to the comment value itself
        else:
            # This is a regular MPN key, find the row and get MPN
            for idx, row in df.iterrows():
                mpn_col = _mapped_col(df, column_map, 'mpn')
                if mpn_col and str(row[mpn_col]).strip().upper() == key:
                    return str(row[mpn_col]).strip()
            return key  # Fallback to the key itself
    
    # Find differences
    new_parts = []
    removed_parts = []
    modified_parts = []
    unchanged_parts = []
    unrecognized_parts = []

    # ── Duplicate-MPN warning ─────────────────────────────────────────────
    # Today the lookup is first-row-wins for duplicate MPNs, silently dropping
    # subsequent occurrences. Surface those so the user can clean their
    # source data.
    duplicate_warnings: list[dict] = []
    def _dups(df, key_series, file_label):
        seen: dict = {}
        for idx, k in key_series.items():
            if not k or k.startswith('COMMENT_'):
                continue
            seen.setdefault(k, []).append(idx)
        for k, indices in seen.items():
            if len(indices) > 1:
                duplicate_warnings.append({
                    'file': file_label,
                    'mpn': k,
                    'occurrences': len(indices),
                    'lines': [int(i) + 2 for i in indices],
                })
    _dups(df1, key1, 'file1')
    _dups(df2, key2, 'file2')

    # ── Fuzzy MPN pairing pass ────────────────────────────────────────────
    # Real BOMs often have the SAME physical part appear with slightly
    # different MPN strings across revisions: a hyphen added/removed, a
    # trailing suffix added ("BC547" → "BC547BTA"), or a typo. Without this,
    # those rows show up as one "Removed" + one "New" — confusing the user
    # who knows it's actually a renamed part. We pair them up here and
    # surface them as Modified rows with both MPNs filled in, plus an
    # explicit MPN_Changed flag so callers can render them differently.
    only_in_1 = set1 - set2
    only_in_2 = set2 - set1
    fuzzy_pairs: list[tuple[str, str]] = []  # (key_in_1, key_in_2)
    # Build a set of user-rejected pairs (canonical form on both sides) so
    # we can skip them in the fuzzy pass.
    rejected_pairs = set()
    if ignore_pairs:
        for a, b in ignore_pairs:
            rejected_pairs.add((_ai_normalize_mpn(a), _ai_normalize_mpn(b)))

    if only_in_1 and only_in_2:
        # Skip COMMENT_-prefixed keys (those aren't real MPNs)
        candidates_1 = [k for k in only_in_1 if not k.startswith('COMMENT_')]
        candidates_2 = [k for k in only_in_2 if not k.startswith('COMMENT_')]
        used_2: set = set()
        for k1 in candidates_1:
            remaining = [k for k in candidates_2 if k not in used_2]
            if not remaining:
                break
            # Use canonical form (strip punctuation) for similarity
            canon1 = _ai_normalize_mpn(k1)
            canon_remaining = {_ai_normalize_mpn(k): k for k in remaining}
            match = find_fuzzy_mpn_match(canon1, list(canon_remaining.keys()), threshold=fuzzy_threshold)
            if match is None:
                continue
            matched_canon, _score = match
            # Respect user rejection list
            if (canon1, matched_canon) in rejected_pairs:
                continue
            k2 = canon_remaining[matched_canon]
            fuzzy_pairs.append((k1, k2))
            used_2.add(k2)

    # Apply pairs: remove from the only-in-X sets, append to modified_parts
    paired_in_1 = {p[0] for p in fuzzy_pairs}
    paired_in_2 = {p[1] for p in fuzzy_pairs}

    for k1, k2 in fuzzy_pairs:
        idx1 = row1_by_key.get(k1)
        idx2 = row2_by_key.get(k2)
        if idx1 is None or idx2 is None:
            continue
        modified_parts.append({
            'MPN': _get_mpn_by_index(df1, idx1, map1),
            'File1 MPN': _get_mpn_by_index(df1, idx1, map1),
            'File2 MPN': _get_mpn_by_index(df2, idx2, map2),
            'Ref Des/LOC': _get_value_by_index(df1, idx1, map1, 'refdes'),
            'File1 Ref Des': _get_value_by_index(df1, idx1, map1, 'refdes'),
            'File2 Ref Des': _get_value_by_index(df2, idx2, map2, 'refdes'),
            'File1 Qty': _get_value_by_index(df1, idx1, map1, 'qty'),
            'File2 Qty': _get_value_by_index(df2, idx2, map2, 'qty'),
            'File1 Description': _get_value_by_index(df1, idx1, map1, 'description'),
            'File2 Description': _get_value_by_index(df2, idx2, map2, 'description'),
            'File1 Line': idx1 + 2,
            'File2 Line': idx2 + 2,
            'MPN_Changed': True,
        })

    # New parts (in File 2, not in File 1)
    for k in only_in_2:  # O(N)
        if k in paired_in_2:
            continue
        idx2 = row2_by_key.get(k)
        if idx2 is None:
            safe_print(f"Warning: Could not find valid index for new part key '{k}'")
            continue
        original_mpn = _get_mpn_by_index(df2, idx2, map2)
        refdes = _get_value_by_index(df2, idx2, map2, 'refdes')
        line_idx = idx2
        line_number = line_idx + 2  # +2 because Excel is 1-indexed and we have header row
        
        new_parts.append({
            'MPN': original_mpn,
            'Ref Des/LOC': refdes,
            'Qty': _get_value_by_index(df2, idx2, map2, 'qty'),
            'Description': _get_value_by_index(df2, idx2, map2, 'description'),
            'Line Number': line_number
        })
    
    # Removed parts (in File 1, not in File 2)
    for k in only_in_1:  # O(N)
        if k in paired_in_1:
            continue
        idx1 = row1_by_key.get(k)
        if idx1 is not None:
            # Use the key 'k' directly since we already have it
            original_mpn = _get_mpn_by_index_with_comment_fallback(df1, idx1, map1, k)
            refdes = _get_value_by_index(df1, idx1, map1, 'refdes')
            line_idx = idx1
            line_number = line_idx + 2  # +2 because Excel is 1-indexed and we have header row
            
            removed_parts.append({
                'MPN': original_mpn,
                'Ref Des/LOC': refdes,
                'Qty': _get_value_by_index(df1, idx1, map1, 'qty'),
                'Description': _get_value_by_index(df1, idx1, map1, 'description'),
                'Line Number': line_number
            })
        else:
            # Key not found in row1_by_key, use the key itself
            if k.startswith('COMMENT_'):
                # Extract the comment value
                comment_val = k[8:]  # Remove 'COMMENT_' prefix
                # Find the row with this comment
                comment_col = None
                for col in df1.columns:
                    if 'comment' in str(col).lower():
                        comment_col = col
                        break
                
                if comment_col:
                    # Find the row with this comment
                    for idx, row in df1.iterrows():
                        if str(row[comment_col]).strip().upper() == comment_val:
                            removed_parts.append({
                                'MPN': str(row[comment_col]).strip(),
                                'Ref Des/LOC': _get_value_by_index(df1, idx, map1, 'refdes'),
                                'Qty': _get_value_by_index(df1, idx, map1, 'qty'),
                                'Description': _get_value_by_index(df1, idx, map1, 'description'),
                                'Line Number': idx + 2 if idx is not None else 'Unknown'
                            })
                            break
                    else:
                        # Comment not found, add with comment value
                        removed_parts.append({
                            'MPN': comment_val,
                            'Ref Des/LOC': 'N/A',
                            'Qty': 'N/A',
                            'Description': 'N/A',
                            'Line Number': 'N/A'
                        })
                else:
                    # No comment column found
                    removed_parts.append({
                        'MPN': comment_val,
                        'Ref Des/LOC': 'N/A',
                        'Qty': 'N/A',
                        'Description': 'N/A',
                        'Line Number': 'N/A'
                    })
            else:
                # Regular MPN key
                original_mpn = _get_mpn_by_key(df1, k, map1)
                removed_parts.append({
                    'MPN': original_mpn,
                    'Ref Des/LOC': 'N/A',
                    'Qty': 'N/A',
                    'Description': 'N/A',
                    'Line Number': 'N/A'
                })
    
    # Modified parts (same part, different qty/description)
    for k in set1 & set2:  # O(N)
        idx1 = row1_by_key.get(k)
        idx2 = row2_by_key.get(k)
        
        # Skip if we can't find valid indices for both files
        if idx1 is None or idx2 is None:
            safe_print(f"Warning: Could not find valid indices for key '{k}' (idx1={idx1}, idx2={idx2})")
            continue
        qty1 = _get_value_by_index(df1, idx1, map1, 'qty')
        qty2 = _get_value_by_index(df2, idx2, map2, 'qty')
        desc1 = _get_value_by_index(df1, idx1, map1, 'description')
        desc2 = _get_value_by_index(df2, idx2, map2, 'description')
        
        # Smart quantity normalization: handles unit suffixes ("10 pcs"),
        # SI prefixes ("10K" → 10000), european decimals, and whole-number
        # floats. Falls back to a stripped string when nothing parses.
        def normalize_qty(qty_str):
            if pd.isna(qty_str) or qty_str == '' or str(qty_str).lower() == 'nan':
                return ''
            num = _ai_normalize_quantity(qty_str)
            if num is None:
                return str(qty_str).strip()
            if num == int(num):
                return str(int(num))
            return str(num)

        qty1_norm = normalize_qty(qty1)
        qty2_norm = normalize_qty(qty2)
        
        # Normalize descriptions
        desc1_norm = norm(desc1)
        desc2_norm = norm(desc2)
        
        # Check for differences
        qty_changed = qty1_norm != qty2_norm
        desc_changed = desc1_norm != desc2_norm
        
        # Check if REF DES has changed (normalize and compare)
        refdes1 = _get_value_by_index(df1, idx1, map1, 'refdes')
        refdes2 = _get_value_by_index(df2, idx2, map2, 'refdes')
        
        # Normalize REF DES for comparison (handle case sensitivity and whitespace)
        def normalize_refdes(refdes_str):
            if pd.isna(refdes_str) or refdes_str == '' or str(refdes_str).lower() == 'nan':
                return ''
            return str(refdes_str).strip().upper()
        
        refdes1_norm = normalize_refdes(refdes1)
        refdes2_norm = normalize_refdes(refdes2)
        refdes_changed = refdes1_norm != refdes2_norm

        # Manufacturer + Vendor diff (NEW). Same MPN with different
        # manufacturer is a "spec change" worth flagging — packaging,
        # supplier qualification, etc.
        def _val(df, idx, m, want):
            for col in df.columns:
                col_lower = str(col).lower()
                if want == 'manufacturer' and (col_lower in {'manufacturer','mfg','mfr'} or 'manufacturer' in col_lower or 'mfg' in col_lower or 'mfr' in col_lower) and 'part' not in col_lower:
                    try:
                        v = df.at[idx, col]
                        return '' if pd.isna(v) else str(v).strip()
                    except Exception:
                        return ''
                if want == 'vendor' and col_lower in {'vendor','supplier','source'}:
                    try:
                        v = df.at[idx, col]
                        return '' if pd.isna(v) else str(v).strip()
                    except Exception:
                        return ''
            return ''
        mfg1 = _val(df1, idx1, map1, 'manufacturer')
        mfg2 = _val(df2, idx2, map2, 'manufacturer')
        vendor1 = _val(df1, idx1, map1, 'vendor')
        vendor2 = _val(df2, idx2, map2, 'vendor')
        mfg_changed = mfg1.upper() != mfg2.upper() and (mfg1 or mfg2)
        vendor_changed = vendor1.upper() != vendor2.upper() and (vendor1 or vendor2)

        # Description-drift heuristic: same MPN, descriptions textually
        # different but token_set similarity < 75 — flagged as a soft
        # "review" finding, not blocking.
        try:
            desc_sim = description_similarity(desc1, desc2)
        except Exception:
            desc_sim = 1.0 if desc1_norm == desc2_norm else 0.0
        desc_drift = desc_sim < 0.75 and (str(desc1).strip() and str(desc2).strip())
        
        # Check if MPN has changed (raw values, not normalized keys)
        mpn1 = _get_value_by_index(df1, idx1, map1, 'mpn')
        mpn2 = _get_value_by_index(df2, idx2, map2, 'mpn')
        
        # Normalize MPN for comparison (preserve original formatting but compare consistently)
        def normalize_mpn_for_comparison(mpn_str):
            if pd.isna(mpn_str) or mpn_str == '' or str(mpn_str).lower() == 'nan':
                return ''
            return str(mpn_str).strip()
        
        mpn1_norm = normalize_mpn_for_comparison(mpn1)
        mpn2_norm = normalize_mpn_for_comparison(mpn2)
        mpn_changed = mpn1_norm != mpn2_norm
        
        safe_print(f"Comparing part {k}:")
        safe_print(f"  MPN1: '{mpn1}' -> '{mpn1_norm}'")
        safe_print(f"  MPN2: '{mpn2}' -> '{mpn2_norm}'")
        safe_print(f"  MPN changed: {mpn_changed}")
        safe_print(f"  Qty1: '{qty1}' -> '{qty1_norm}'")
        safe_print(f"  Qty2: '{qty2}' -> '{qty2_norm}'")
        safe_print(f"  Qty changed: {qty_changed}")
        safe_print(f"  RefDes1: '{refdes1}' -> '{refdes1_norm}'")
        safe_print(f"  RefDes2: '{refdes2}' -> '{refdes2_norm}'")
        safe_print(f"  RefDes changed: {refdes_changed}")
        safe_print(f"  Desc1: '{desc1}' -> '{desc1_norm}'")
        safe_print(f"  Desc2: '{desc2}' -> '{desc2_norm}'")
        safe_print(f"  Desc changed: {desc_changed}")
        
        # Add to modified_parts if ANY field has changes (qty, refdes, description,
        # manufacturer, or vendor). MPN is the same since we're in the
        # intersection of sets.
        if qty_changed or refdes_changed or desc_changed or mfg_changed or vendor_changed:
            safe_print(f"  -> Adding to modified parts (ANY field changed)")
            # Get original values via O(1) index lookups
            original_mpn1 = _get_mpn_by_index(df1, idx1, map1)
            original_mpn2 = _get_mpn_by_index(df2, idx2, map2)
            refdes1 = _get_value_by_index(df1, idx1, map1, 'refdes')
            refdes2 = _get_value_by_index(df2, idx2, map2, 'refdes')
            line1_idx = idx1
            line2_idx = idx2
            line1_number = line1_idx + 2  # +2 because Excel is 1-indexed and we have header row
            line2_number = line2_idx + 2  # +2 because Excel is 1-indexed and we have header row
            
            # Debug: Log the ref des values being added
            safe_print(f"DEBUG: Adding modified part {original_mpn1}")
            safe_print(f"  refdes1 (File1): '{refdes1}' (type: {type(refdes1)})")
            safe_print(f"  refdes2 (File2): '{refdes2}' (type: {type(refdes2)})")
            
            modified_part = {
                'MPN': original_mpn1,  # Use File1 MPN for display
                'Ref Des/LOC': refdes1,  # Use File1 Ref Des for display
                'File1 Ref Des': refdes1,
                'File2 Ref Des': refdes2,
                'File1 Qty': qty1,
                'File2 Qty': qty2,
                'File1 Description': desc1,
                'File2 Description': desc2,
                'File1 Line': line1_number,
                'File2 Line': line2_number,
                'File1 Manufacturer': mfg1,
                'File2 Manufacturer': mfg2,
                'File1 Vendor': vendor1,
                'File2 Vendor': vendor2,
                'Description Similarity': round(desc_sim, 2),
                'flags': {
                    'qty': qty_changed,
                    'refdes': refdes_changed,
                    'description': desc_changed,
                    'manufacturer': mfg_changed,
                    'vendor': vendor_changed,
                    'description_drift': desc_drift,
                },
            }
            safe_print(f"  Final modified_part: {modified_part}")
            modified_parts.append(modified_part)
        else:
            safe_print(f"  -> Adding to unchanged parts (no fields changed)")
            if not qty_changed:
                safe_print(f"    - QTY unchanged")
            if not refdes_changed:
                safe_print(f"    - REF DES unchanged")
            # Get original MPN value for display
            original_mpn = _get_mpn_by_index(df1, idx1, map1)
            refdes = _get_value_by_index(df1, idx1, map1, 'refdes')
            line_idx = idx1
            line_number = line_idx + 2  # +2 because Excel is 1-indexed and we have header row
            
            unchanged_parts.append({
                'MPN': original_mpn,
                'Ref Des/LOC': refdes,
                'Qty': qty1,
                'Description': desc1,
                'Line Number': line_number
            })
    
    # Description-drift bucket — same MPN, big description rewrite.
    # We list these separately so they're easy to triage.
    description_drift_parts = [
        m for m in modified_parts
        if isinstance(m.get('flags'), dict) and m['flags'].get('description_drift')
    ]

    # Summary statistics
    summary_stats = {
        'total_parts_file1': len(set1),
        'total_parts_file2': len(set2),
        'new_parts_count': len(new_parts),
        'removed_parts_count': len(removed_parts),
        'modified_parts_count': len(modified_parts),
        'unchanged_parts_count': len(unchanged_parts),
        'unrecognized_parts_count': len(unrecognized_parts),
        'mpn_renamed_count': sum(1 for m in modified_parts if m.get('MPN_Changed')),
        'duplicate_mpn_count': len(duplicate_warnings),
        'description_drift_count': len(description_drift_parts),
        'fuzzy_threshold': fuzzy_threshold,
    }
    
    # Convert all values to strings for web display
    def to_str_dict_list(lst):
        def clean_value(v):
            if pd.isna(v) or v == '' or str(v).lower() in ['nan', 'none', 'null']:
                return 'N/A'
            # Format numbers properly
            if isinstance(v, (int, float)) and not pd.isna(v):
                if v == int(v):
                    return str(int(v))
                else:
                    return str(v)
            val_str = str(v).strip()
            if not val_str or val_str.lower() in ['nan', 'none', 'null']:
                return 'N/A'
            return val_str
        
        return [{k: clean_value(v) for k, v in row.items()} for row in lst]
    
    return {
        'new_parts': to_str_dict_list(new_parts),
        'removed_parts': to_str_dict_list(removed_parts),
        'modified_parts': to_str_dict_list(modified_parts),
        'unchanged_parts': to_str_dict_list(unchanged_parts),
        'unrecognized_parts': to_str_dict_list(unrecognized_parts),
        'description_drift_parts': to_str_dict_list(description_drift_parts),
        'duplicate_mpn_warnings': duplicate_warnings,
        'summary_stats': summary_stats,
    }

def compare_boms_manual(file1, file2, manual_map1, manual_map2,
                         fuzzy_threshold: float = 0.88,
                         ignore_pairs: Optional[List[Tuple[str, str]]] = None):
    """Compare two BOM files using manually specified column mappings."""
    safe_print("Starting manual BOM comparison...")

    # Read both files without auto-detection
    ext1 = os.path.splitext(file1)[1].lower()
    ext2 = os.path.splitext(file2)[1].lower()

    # Read files with headers (cached so we don't read the same xlsx 4x)
    df1_raw = read_excel_cached(file1, header=None)
    df2_raw = read_excel_cached(file2, header=None)

    # Find header rows automatically (we still need this to know where data starts)
    header_row1, _ = find_header_row_and_map(file1)
    header_row2, _ = find_header_row_and_map(file2)

    # Read files with proper headers (cached; we copy since downstream mutates)
    df1 = read_excel_cached(file1, header=header_row1).copy()
    df2 = read_excel_cached(file2, header=header_row2).copy()

    safe_print(f"File 1 columns: {list(df1.columns)}")
    safe_print(f"File 2 columns: {list(df2.columns)}")
    safe_print(f"Manual mapping 1: {manual_map1}")
    safe_print(f"Manual mapping 2: {manual_map2}")

    # Validate that selected columns exist
    for key, col_name in manual_map1.items():
        if col_name not in df1.columns:
            raise ValueError(f"Column '{col_name}' not found in file 1. Available: {list(df1.columns)}")

    for key, col_name in manual_map2.items():
        if col_name not in df2.columns:
            raise ValueError(f"Column '{col_name}' not found in file 2. Available: {list(df2.columns)}")

    # Ensure MPN columns are specified
    if 'mpn' not in manual_map1 or 'mpn' not in manual_map2:
        raise ValueError("MPN column must be specified for both files")

    # Convert MPN columns to string to preserve formatting
    mpn_col1 = manual_map1['mpn']
    mpn_col2 = manual_map2['mpn']
    df1[mpn_col1] = df1[mpn_col1].astype(str)
    df2[mpn_col2] = df2[mpn_col2].astype(str)

    safe_print(f"Using MPN columns: '{mpn_col1}' and '{mpn_col2}'")

    # Now call the comparison logic (reuse the logic from compare_boms but with manual mappings)
    return _perform_comparison_with_mappings(
        df1, df2, manual_map1, manual_map2, header_row1, header_row2,
        fuzzy_threshold=fuzzy_threshold, ignore_pairs=ignore_pairs,
    )

def _perform_comparison_with_mappings(df1, df2, map1, map2, header_row1, header_row2,
                                       fuzzy_threshold: float = 0.88,
                                       ignore_pairs: Optional[List[Tuple[str, str]]] = None):
    """Perform the actual comparison using provided column mappings."""

    # Normalize values (reuse from compare_boms)
    def norm(val):
        """Normalize values while preserving original MPN formatting."""
        if pd.isna(val) or val == '' or str(val).lower() in ['nan', 'none', 'null', '']:
            return ''

        val_str = str(val).strip()

        if not val_str or val_str.lower() in ['nan', 'none', 'null']:
            return ''

        normalized = val_str.upper()

        # Handle electronic component value variations
        if normalized.endswith('R') and len(normalized) > 1:
            try:
                float(normalized[:-1])
                normalized = normalized[:-1]
            except ValueError:
                pass

        return normalized

    # Create comparison keys
    mpn_col1 = map1['mpn']
    mpn_col2 = map2['mpn']

    # Generate keys for each row
    key1 = df1[mpn_col1].apply(norm)
    key2 = df2[mpn_col2].apply(norm)

    # Filter out empty keys
    mask1 = key1 != ''
    mask2 = key2 != ''

    # Build sets of MPNs
    set1 = set(key1[mask1])
    set2 = set(key2[mask2])

    # Build lookup dictionaries
    row1_by_key = {}
    for idx, k in key1.items():
        if k and k not in row1_by_key:
            row1_by_key[k] = idx

    row2_by_key = {}
    for idx, k in key2.items():
        if k and k not in row2_by_key:
            row2_by_key[k] = idx

    # Helper functions
    def _get_value_by_mapping(df, row_index, column_map, column_name):
        if column_name not in column_map or row_index not in df.index:
            return 'N/A'
        col = column_map[column_name]
        return df.at[row_index, col] if col in df.columns else 'N/A'

    def _get_mpn_by_index(df, row_index, column_map):
        val = _get_value_by_mapping(df, row_index, column_map, 'mpn')
        if pd.isna(val):
            return 'N/A'
        if isinstance(val, (int, float)) and not pd.isna(val) and val == int(val):
            return str(int(val))
        return str(val).strip()

    # Find differences
    new_parts = []
    removed_parts = []
    modified_parts = []
    unchanged_parts = []

    # ── Fuzzy MPN pairing pass (manual flow) ─────────────────────────────
    # Mirror the auto-flow's behavior so renamed-MPN detection works whether
    # the user picks columns themselves or uses auto-detection.
    only_in_1 = set1 - set2
    only_in_2 = set2 - set1
    rejected_pairs = set()
    if ignore_pairs:
        for a, b in ignore_pairs:
            rejected_pairs.add((_ai_normalize_mpn(a), _ai_normalize_mpn(b)))

    fuzzy_pairs: list = []
    if only_in_1 and only_in_2:
        used_2: set = set()
        for k1 in only_in_1:
            remaining = [k for k in only_in_2 if k not in used_2]
            if not remaining:
                break
            canon1 = _ai_normalize_mpn(k1)
            canon_remaining = {_ai_normalize_mpn(k): k for k in remaining}
            match = find_fuzzy_mpn_match(canon1, list(canon_remaining.keys()), threshold=fuzzy_threshold)
            if match is None:
                continue
            matched_canon, _score = match
            if (canon1, matched_canon) in rejected_pairs:
                continue
            k2 = canon_remaining[matched_canon]
            fuzzy_pairs.append((k1, k2))
            used_2.add(k2)

    paired_1 = {p[0] for p in fuzzy_pairs}
    paired_2 = {p[1] for p in fuzzy_pairs}

    for k1, k2 in fuzzy_pairs:
        idx1 = row1_by_key.get(k1)
        idx2 = row2_by_key.get(k2)
        if idx1 is None or idx2 is None:
            continue
        modified_parts.append({
            'MPN': _get_mpn_by_index(df1, idx1, map1),
            'File1 MPN': _get_mpn_by_index(df1, idx1, map1),
            'File2 MPN': _get_mpn_by_index(df2, idx2, map2),
            'Ref Des/LOC': _get_value_by_mapping(df1, idx1, map1, 'refdes'),
            'File1 Ref Des': _get_value_by_mapping(df1, idx1, map1, 'refdes'),
            'File2 Ref Des': _get_value_by_mapping(df2, idx2, map2, 'refdes'),
            'File1 Qty': _get_value_by_mapping(df1, idx1, map1, 'qty'),
            'File2 Qty': _get_value_by_mapping(df2, idx2, map2, 'qty'),
            'File1 Description': _get_value_by_mapping(df1, idx1, map1, 'description'),
            'File2 Description': _get_value_by_mapping(df2, idx2, map2, 'description'),
            'File1 Line': idx1 + header_row1 + 2,
            'File2 Line': idx2 + header_row2 + 2,
            'MPN_Changed': True,
        })

    # New parts (in File 2, not in File 1, minus paired)
    for k in only_in_2:
        if k in paired_2:
            continue
        idx2 = row2_by_key.get(k)
        if idx2 is None:
            continue

        original_mpn = _get_mpn_by_index(df2, idx2, map2)
        line_number = idx2 + header_row2 + 2

        new_parts.append({
            'MPN': original_mpn,
            'Ref Des/LOC': _get_value_by_mapping(df2, idx2, map2, 'refdes'),
            'Qty': _get_value_by_mapping(df2, idx2, map2, 'qty'),
            'Description': _get_value_by_mapping(df2, idx2, map2, 'description'),
            'Line Number': line_number
        })

    # Removed parts (in File 1, not in File 2, minus paired)
    for k in only_in_1:
        if k in paired_1:
            continue
        idx1 = row1_by_key.get(k)
        if idx1 is None:
            continue

        original_mpn = _get_mpn_by_index(df1, idx1, map1)
        line_number = idx1 + header_row1 + 2

        removed_parts.append({
            'MPN': original_mpn,
            'Ref Des/LOC': _get_value_by_mapping(df1, idx1, map1, 'refdes'),
            'Qty': _get_value_by_mapping(df1, idx1, map1, 'qty'),
            'Description': _get_value_by_mapping(df1, idx1, map1, 'description'),
            'Line Number': line_number
        })

    # Modified/Unchanged parts (same MPN in both files)
    for k in set1 & set2:
        idx1 = row1_by_key.get(k)
        idx2 = row2_by_key.get(k)

        if idx1 is None or idx2 is None:
            continue

        qty1 = _get_value_by_mapping(df1, idx1, map1, 'qty')
        qty2 = _get_value_by_mapping(df2, idx2, map2, 'qty')
        desc1 = _get_value_by_mapping(df1, idx1, map1, 'description')
        desc2 = _get_value_by_mapping(df2, idx2, map2, 'description')
        refdes1 = _get_value_by_mapping(df1, idx1, map1, 'refdes')
        refdes2 = _get_value_by_mapping(df2, idx2, map2, 'refdes')

        # Normalize for comparison
        def normalize_qty(qty_str):
            if pd.isna(qty_str) or qty_str == '' or str(qty_str).lower() == 'nan':
                return ''
            try:
                qty_float = float(str(qty_str))
                if qty_float == int(qty_float):
                    return str(int(qty_float))
                else:
                    return str(qty_float)
            except:
                return str(qty_str).strip()

        qty1_norm = normalize_qty(qty1)
        qty2_norm = normalize_qty(qty2)
        desc1_norm = norm(desc1)
        desc2_norm = norm(desc2)

        def normalize_refdes(refdes_str):
            if pd.isna(refdes_str) or refdes_str == '' or str(refdes_str).lower() == 'nan':
                return ''
            return str(refdes_str).strip().upper()

        refdes1_norm = normalize_refdes(refdes1)
        refdes2_norm = normalize_refdes(refdes2)

        # Check for differences
        qty_changed = qty1_norm != qty2_norm
        desc_changed = desc1_norm != desc2_norm
        refdes_changed = refdes1_norm != refdes2_norm

        if qty_changed or desc_changed or refdes_changed:
            # Modified part
            original_mpn = _get_mpn_by_index(df1, idx1, map1)
            line1_number = idx1 + header_row1 + 2
            line2_number = idx2 + header_row2 + 2

            modified_parts.append({
                'MPN': original_mpn,
                'Ref Des/LOC': refdes1,
                'File1 Ref Des': refdes1,
                'File2 Ref Des': refdes2,
                'File1 Qty': qty1,
                'File2 Qty': qty2,
                'File1 Description': desc1,
                'File2 Description': desc2,
                'File1 Line': line1_number,
                'File2 Line': line2_number
            })
        else:
            # Unchanged part
            original_mpn = _get_mpn_by_index(df1, idx1, map1)
            line_number = idx1 + header_row1 + 2

            unchanged_parts.append({
                'MPN': original_mpn,
                'Ref Des/LOC': refdes1,
                'Qty': qty1,
                'Description': desc1,
                'Line Number': line_number
            })

    # Summary statistics
    summary_stats = {
        'total_parts_file1': len(set1),
        'total_parts_file2': len(set2),
        'new_parts_count': len(new_parts),
        'removed_parts_count': len(removed_parts),
        'modified_parts_count': len(modified_parts),
        'unchanged_parts_count': len(unchanged_parts),
        'unrecognized_parts_count': 0,
        'mpn_renamed_count': sum(1 for m in modified_parts if m.get('MPN_Changed')),
        'fuzzy_threshold': fuzzy_threshold,
    }

    # Convert all values to strings for web display
    def to_str_dict_list(lst):
        def clean_value(v):
            if pd.isna(v) or v == '' or str(v).lower() in ['nan', 'none', 'null']:
                return 'N/A'
            if isinstance(v, (int, float)) and not pd.isna(v):
                if v == int(v):
                    return str(int(v))
                else:
                    return str(v)
            val_str = str(v).strip()
            if not val_str or val_str.lower() in ['nan', 'none', 'null']:
                return 'N/A'
            return val_str

        return [{k: clean_value(v) for k, v in row.items()} for row in lst]

    return {
        'new_parts': to_str_dict_list(new_parts),
        'removed_parts': to_str_dict_list(removed_parts),
        'modified_parts': to_str_dict_list(modified_parts),
        'unchanged_parts': to_str_dict_list(unchanged_parts),
        'unrecognized_parts': [],
        'summary_stats': summary_stats
    } 