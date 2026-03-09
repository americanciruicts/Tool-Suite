"""
PDF to Excel BOM Extraction Tool

This module handles extraction of Bill of Materials (BOM) data from digitally generated PDFs
and converts them to clean Excel files compatible with the BOM Comparison tool.

Key Features:
- Validates digital PDFs (rejects scanned/image-only PDFs)
- Detects BOM tables with confidence scoring
- Normalizes extracted data (handles merged cells, multi-line items, duplicate headers)
- Maps to standardized BOM schema (MPN, Qty, Ref Des, Description)
- Generates Excel with no merged cells
"""

import pdfplumber
import pypdf
import pandas as pd
import tempfile
import os
from typing import Dict, List, Tuple, Optional
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from excel_tool import find_header_row_and_map


# Error messages for graceful failures
ERROR_MESSAGES = {
    'scanned_pdf': (
        "This PDF appears to be a scanned document or image-only. "
        "Please provide a digitally generated PDF with selectable text."
    ),
    'no_table': (
        "Could not detect a BOM table in this PDF. "
        "Ensure the PDF contains a table with Part Number, Quantity, and Description columns."
    ),
    'no_mpn': (
        "No part number column found. "
        "BOM must include a column for MPN, Part Number, P/N, or similar."
    ),
    'corrupt': (
        "PDF file is corrupted or invalid. Please try re-exporting from source application."
    ),
    'encrypted': (
        "Password-protected PDFs are not supported. Please provide unencrypted PDF."
    ),
    'low_confidence': (
        "BOM table detected with low confidence. Results may require manual review."
    )
}


# BOM header keywords with weights for table detection
# Enhanced to support: Manufacturer, MPN, Qty, Description, RefDes, Vendor, Vendor P/N, Item #, Customer P/N
HEADER_KEYWORDS = {
    # MPN / Part Number keywords
    'mpn': 10, 'part number': 10, 'mfg pn': 10, 'p/n': 8, 'part #': 10,
    'manufacturer part number': 10, 'mfg part number': 10, 'model number': 10,
    'part no': 9, 'part_number': 9, 'mfr pn': 10, 'mfr part': 9,

    # Manufacturer keywords
    'manufacturer': 9, 'mfg': 8, 'mfr': 8, 'vendor': 7, 'supplier': 7,
    'manufacturer name': 9, 'mfg name': 8,

    # Vendor/Supplier keywords
    'vendor part number': 8, 'supplier part number': 8, 'vendor pn': 7,
    'supplier pn': 7, 'vendor p/n': 7, 'supplier p/n': 7,

    # Customer Part Number keywords
    'customer pn': 8, 'customer part number': 8, 'customer p/n': 7,
    'internal pn': 7, 'company pn': 7, 'kjr p/n': 9,

    # Quantity keywords
    'quantity': 8, 'qty': 8, 'count': 5, 'amount': 5, 'qty required': 7,
    'qty per': 7, 'qty/assy': 7, 'per assy': 6,

    # Reference Designator keywords
    'refdes': 7, 'ref des': 7, 'designator': 7, 'location': 6, 'loc': 6,
    'reference designator': 8, 'reference designation': 7, 'refdes/loc': 7,
    'ref desg': 7, 'reference': 6,

    # Description keywords
    'description': 8, 'desc': 7, 'notes': 5, 'comment': 5, 'remarks': 4,
    'part description': 8, 'component description': 8, 'comments': 5,

    # Item/Line keywords
    'item': 6, 'line': 4, 'item number': 7, 'item #': 6, 'line number': 5,
    'line #': 4, 'rev': 3, 'revision': 3
}


def validate_digital_pdf(pdf_path: str) -> None:
    """
    Validate PDF is digitally generated (not scanned).

    Args:
        pdf_path: Path to PDF file

    Raises:
        ValueError: If PDF is scanned/image-only, encrypted, corrupt, or has no pages
    """
    try:
        # Check for encryption using pypdf
        try:
            with open(pdf_path, 'rb') as f:
                pdf_reader = pypdf.PdfReader(f)
                if pdf_reader.is_encrypted:
                    raise ValueError(ERROR_MESSAGES['encrypted'])
        except Exception as e:
            if "encrypted" in str(e).lower():
                raise ValueError(ERROR_MESSAGES['encrypted'])

        # Check for text content using pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                raise ValueError("PDF has no pages")

            # Check first 3 pages for text content
            text_found = False
            for page in pdf.pages[:3]:
                text = page.extract_text()
                # Lower threshold to 20 chars to catch minimal text PDFs
                if text and len(text.strip()) > 20:
                    text_found = True
                    break

            if not text_found:
                raise ValueError(ERROR_MESSAGES['scanned_pdf'])

    except ValueError:
        # Re-raise our custom validation errors
        raise
    except Exception as e:
        if "encrypted" in str(e).lower():
            raise ValueError(ERROR_MESSAGES['encrypted'])
        # For other errors, assume corrupt PDF
        raise ValueError(ERROR_MESSAGES['corrupt'])


def _headers_match(header1: List, header2: List) -> bool:
    """
    Check if two headers represent the same table structure.

    Args:
        header1: First header row
        header2: Second header row

    Returns:
        True if headers match with >= 80% similarity
    """
    if len(header1) != len(header2):
        return False

    matches = sum(1 for h1, h2 in zip(header1, header2)
                  if str(h1).lower().strip() == str(h2).lower().strip())

    return matches / len(header1) >= 0.8 if header1 else False


def _extract_bom_by_word_positions(pdf_path: str) -> Optional[Dict]:
    """
    Extract BOM data using word-level positions from pdfplumber.

    This is the most accurate method as it uses the actual x-coordinates
    of words in the PDF to determine column boundaries.
    """
    import re

    bom_keywords = [
        'item', 'number', 'revision', 'rev', 'description', 'desc',
        'lifecycle', 'phase', 'quantity', 'qty', 'manufacturer', 'mfg', 'mfr',
        'part', 'mpn', 'p/n', 'distributor', 'vendor', 'supplier',
        'reference', 'refdes', 'designator', 'comments', 'notes', 'model',
        'bom', 'cost', 'assy', 'per'
    ]

    with pdfplumber.open(pdf_path) as pdf:
        all_rows = []
        header_cols = None
        header_y = None

        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words()
            if not words:
                continue

            # Group words by y-position (same line)
            lines_dict = {}
            for word in words:
                # Round y to group words on same line (tolerance of 8 units for varying baselines)
                y_key = round(word['top'] / 8) * 8
                if y_key not in lines_dict:
                    lines_dict[y_key] = []
                lines_dict[y_key].append(word)

            # Sort lines by y position
            sorted_y = sorted(lines_dict.keys())

            for y in sorted_y:
                line_words = sorted(lines_dict[y], key=lambda w: w['x0'])

                # Check if this is a header line
                line_text = ' '.join(w['text'].lower() for w in line_words)
                keyword_count = sum(1 for kw in bom_keywords if kw in line_text)

                if keyword_count >= 3 and header_cols is None:
                    # This is likely the header - extract column boundaries
                    # First, calculate the median gap between words to determine threshold
                    gaps = []
                    for i in range(1, len(line_words)):
                        gap = line_words[i]['x0'] - line_words[i-1]['x1']
                        gaps.append(gap)

                    if gaps:
                        # Use median gap * 1.5 as threshold for column break
                        sorted_gaps = sorted(gaps)
                        median_gap = sorted_gaps[len(sorted_gaps) // 2]
                        gap_threshold = max(median_gap * 1.5, 15)  # At least 15 units
                    else:
                        gap_threshold = 20

                    header_cols = []
                    current_col = []
                    last_x1 = -100

                    for word in line_words:
                        # If gap exceeds threshold, start new column
                        if word['x0'] - last_x1 > gap_threshold and current_col:
                            col_name = ' '.join(w['text'] for w in current_col)
                            col_x0 = current_col[0]['x0']
                            header_cols.append({'name': col_name, 'x0': col_x0})
                            current_col = []

                        current_col.append(word)
                        last_x1 = word['x1']

                    # Don't forget last column
                    if current_col:
                        col_name = ' '.join(w['text'] for w in current_col)
                        col_x0 = current_col[0]['x0']
                        header_cols.append({'name': col_name, 'x0': col_x0})

                    # Add end boundaries - use midpoint between columns
                    for i, col in enumerate(header_cols):
                        if i + 1 < len(header_cols):
                            # Use midpoint between this column's last word and next column's first word
                            col['x1'] = (col['x0'] + header_cols[i + 1]['x0']) / 2 + (header_cols[i + 1]['x0'] - col['x0']) / 2
                            col['x1'] = header_cols[i + 1]['x0'] - 5  # Small buffer before next column
                        else:
                            col['x1'] = 10000  # Last column extends to end

                    header_y = y
                    continue

                # If we have headers, extract data row
                if header_cols and line_words:
                    # Skip if this looks like another header
                    if keyword_count >= 3:
                        continue

                    # Skip header continuation lines (close to header y)
                    if header_y and abs(y - header_y) < 15:
                        continue

                    row_data = {col['name']: '' for col in header_cols}

                    for word in line_words:
                        # Find which column this word belongs to based on x position
                        word_x = word['x0']
                        best_col = None
                        best_dist = float('inf')

                        for col in header_cols:
                            # Calculate distance to column center
                            col_center = (col['x0'] + col['x1']) / 2
                            dist = abs(word_x - col['x0'])

                            # Word belongs to column if it starts within column boundaries
                            if col['x0'] - 10 <= word_x < col['x1'] + 10:
                                if dist < best_dist:
                                    best_dist = dist
                                    best_col = col

                        if best_col:
                            if row_data[best_col['name']]:
                                row_data[best_col['name']] += ' ' + word['text']
                            else:
                                row_data[best_col['name']] = word['text']

                    # Only add if row has meaningful data
                    non_empty = sum(1 for v in row_data.values() if v.strip())
                    if non_empty >= 2:
                        all_rows.append(row_data)

        if not header_cols or not all_rows:
            return None

        # Create DataFrame
        col_names = [col['name'] for col in header_cols]
        df = pd.DataFrame(all_rows, columns=col_names)

        # Filter rows that look like data (not footer/notes)
        def is_data_row(row):
            values = [str(v).strip() for v in row if str(v).strip()]
            if len(values) < 2:
                return False
            # Check for part-number-like values (alphanumeric)
            for v in values:
                if len(v) >= 3 and (any(c.isalpha() for c in v) or any(c.isdigit() for c in v)):
                    return True
            return False

        df = df[df.apply(is_data_row, axis=1)]

        if df.empty:
            return None

        return {
            'table_data': df,
            'confidence': 0.75,  # Higher confidence for word-position method
            'page_numbers': list(range(1, len(pdf.pages) + 1)),
            'header_row': col_names
        }


def _detect_bom_columns_in_header(header_line: str) -> List[Tuple[int, int, str]]:
    """
    Detect BOM column names in a header line and return their positions.

    Returns list of (start_pos, end_pos, column_name) tuples.
    """
    import re

    # Known BOM column names in order of specificity (longest first to avoid partial matches)
    known_columns = [
        'manufacturer part number', 'manufacturer part no', 'manufacturer pn',
        'mfg part number', 'mfr part number', 'vendor part number', 'supplier part number',
        'reference designator', 'reference designation', 'ref designator',
        'lifecycle phase', 'part number', 'part no', 'part #', 'item number', 'item no',
        'item #', 'line number', 'model number', 'model no', 'customer pn',
        'manufacturer', 'description', 'quantity', 'revision', 'comments',
        'distributor', 'supplier', 'vendor', 'refdes', 'ref des', 'phase',
        'item', 'mpn', 'mfg', 'mfr', 'qty', 'rev', 'bom', 'assy', 'cost', 'type',
        'part', 'number', 'per assy', 'uom', 'designator', 'location', 'notes'
    ]

    header_lower = header_line.lower()
    found_columns = []

    # Track which positions have been claimed
    claimed = [False] * len(header_line)

    for col_name in known_columns:
        # Find all occurrences
        start = 0
        while True:
            pos = header_lower.find(col_name, start)
            if pos == -1:
                break

            # Check if this position overlaps with already claimed positions
            end_pos = pos + len(col_name)
            overlap = any(claimed[i] for i in range(pos, min(end_pos, len(claimed))))

            if not overlap:
                # Mark as claimed
                for i in range(pos, min(end_pos, len(claimed))):
                    claimed[i] = True

                # Get the actual text (preserve case)
                actual_name = header_line[pos:end_pos].strip()
                found_columns.append((pos, end_pos, actual_name))

            start = pos + 1

    # Sort by position
    found_columns.sort(key=lambda x: x[0])

    # Adjust end positions to be the start of next column
    result = []
    for i, (start, end, name) in enumerate(found_columns):
        if i + 1 < len(found_columns):
            actual_end = found_columns[i + 1][0]
        else:
            actual_end = len(header_line)
        result.append((start, actual_end, name))

    return result


def _extract_by_column_positions(line: str, col_positions: List[Tuple[int, int, str]]) -> List[str]:
    """
    Extract data from line based on column positions.
    """
    values = []
    padded_line = line.ljust(max(end for _, end, _ in col_positions) if col_positions else len(line))

    for start, end, _ in col_positions:
        value = padded_line[start:end].strip()
        values.append(value)

    return values


def _extract_table_from_text(pdf_path: str) -> Optional[Dict]:
    """
    Fallback: Extract BOM data from text when table extraction fails.

    This handles cases where PDF tables don't have visible gridlines
    and pdfplumber can't detect column boundaries.

    Uses multiple strategies:
    1. Position-based extraction using header column positions
    2. Multi-space splitting for simple cases
    3. Pattern matching for common BOM data types

    Returns:
        Dictionary with table_data, confidence, page_numbers, header_row
        or None if text extraction also fails
    """
    import re

    with pdfplumber.open(pdf_path) as pdf:
        all_text = ""
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                all_text += text + "\n"

        if not all_text.strip():
            return None

        lines = all_text.strip().split('\n')

        # Extended BOM keywords - ordered by priority/specificity
        bom_keywords = [
            'manufacturer part number', 'mfg part number', 'mfr part number',
            'part number', 'part no', 'part #', 'part#', 'p/n',
            'manufacturer', 'mfg', 'mfr',
            'description', 'desc',
            'qty', 'quantity', 'per assy',
            'ref des', 'refdes', 'reference designator', 'designator',
            'model number', 'model no', 'model',
            'revision', 'rev',
            'item', 'bom'
        ]

        # Try to find header line with BOM keywords
        header_line_idx = None
        header_keywords_found = []
        best_header_score = 0

        for idx, line in enumerate(lines[:40]):  # Check first 40 lines
            line_lower = line.lower()
            keywords_in_line = []

            for kw in bom_keywords:
                if kw in line_lower:
                    # Don't double count overlapping keywords
                    already_found = any(kw in existing or existing in kw for existing in keywords_in_line)
                    if not already_found:
                        keywords_in_line.append(kw)

            # Score this line (prefer more keywords, and longer/more specific keywords)
            score = sum(len(kw) for kw in keywords_in_line)

            # At least 2 BOM keywords with good score
            if len(keywords_in_line) >= 2 and score > best_header_score:
                header_line_idx = idx
                header_keywords_found = keywords_in_line
                best_header_score = score

        if header_line_idx is None:
            return None

        header_line = lines[header_line_idx]

        # Strategy 1: Detect known BOM column names in header
        col_positions = _detect_bom_columns_in_header(header_line)

        # Strategy 2: Multi-space splitting as fallback
        header_parts = re.split(r'\s{2,}|\t', header_line)
        header_parts = [h.strip() for h in header_parts if h.strip()]

        # Choose strategy based on quality
        use_position_based = len(col_positions) >= 3 and len(col_positions) <= 15

        if use_position_based:
            # Use detected column names
            header_parts = [name for _, _, name in col_positions]

        if len(header_parts) < 2:
            # Try single-space splitting if multi-space fails
            header_parts = header_line.split()
            if len(header_parts) < 3:
                return None
            use_position_based = False

        data_rows = []

        for line in lines[header_line_idx + 1:]:
            if not line.strip():
                continue

            # Skip lines that look like headers repeated
            line_lower = line.lower()
            header_match_count = sum(1 for kw in header_keywords_found if kw in line_lower)
            if header_match_count >= min(3, len(header_keywords_found)):
                continue

            # Skip lines that are too short
            if len(line.strip()) < 8:
                continue

            # Skip footer/header lines
            skip_patterns = ['page ', 'sheet ', 'revision date', 'date:', 'drawn by',
                           'approved by', 'copyright', 'confidential', 'total:']
            if any(skip in line_lower for skip in skip_patterns):
                continue

            # Skip lines that look like continuation markers or notes
            if line.strip().startswith('---') or line.strip().startswith('==='):
                continue

            # Skip underline rows (common in text-based tables)
            if re.match(r'^[\s_\-=]+$', line):
                continue

            # Extract data
            if use_position_based:
                parts = _extract_by_column_positions(line, col_positions)
            else:
                # Multi-space splitting
                parts = re.split(r'\s{2,}|\t', line)
                parts = [p.strip() for p in parts if p.strip()]

                # If splitting gives too few parts, try single space with smart merging
                if len(parts) < 2:
                    parts = line.split()

                    # Try to merge parts based on expected data patterns
                    # (e.g., descriptions are usually at the end and can have spaces)
                    if len(parts) > len(header_parts):
                        # Assume extra parts belong to description (usually last)
                        merged = parts[:len(header_parts)-1]
                        merged.append(' '.join(parts[len(header_parts)-1:]))
                        parts = merged

            # Remove empty parts from ends but preserve structure
            while parts and not parts[-1]:
                parts.pop()
            while parts and not parts[0]:
                parts.pop(0)

            # Validate: at least 2 non-empty parts
            non_empty = sum(1 for p in parts if p)
            if non_empty < 2:
                continue

            # Pad or trim to match header length
            target_len = len(header_parts)
            while len(parts) < target_len:
                parts.append('')
            if len(parts) > target_len:
                # Merge extra into last column (usually description)
                extra = ' '.join(parts[target_len:])
                parts = parts[:target_len]
                if parts[-1]:
                    parts[-1] = parts[-1] + ' ' + extra
                else:
                    parts[-1] = extra

            data_rows.append(parts)

        if not data_rows:
            return None

        # Create DataFrame
        df = pd.DataFrame(data_rows, columns=header_parts)

        # Filter rows that have at least one value that looks like a part number
        # (alphanumeric with at least some letters and numbers)
        def has_pn_like_value(row):
            for val in row:
                val_str = str(val).strip()
                if len(val_str) >= 3:
                    has_letters = any(c.isalpha() for c in val_str)
                    has_numbers = any(c.isdigit() for c in val_str)
                    if has_letters or has_numbers:
                        return True
            return False

        df = df[df.apply(has_pn_like_value, axis=1)]

        if df.empty:
            return None

        return {
            'table_data': df,
            'confidence': 0.6,  # Lower confidence for text extraction
            'page_numbers': list(range(1, len(pdf.pages) + 1)),
            'header_row': header_parts
        }


def _is_table_data_valid(table: List) -> bool:
    """
    Check if extracted table has valid data distribution.

    Returns False if all data is crammed into one column (extraction failed).
    """
    if not table or len(table) < 2:
        return False

    header = table[0]
    data_rows = table[1:]

    # Filter out completely empty rows
    non_empty_rows = []
    for row in data_rows:
        if any(cell and str(cell).strip() for cell in row):
            non_empty_rows.append(row)

    if not non_empty_rows:
        return False

    # Count how many columns actually have data across non-empty rows
    cols_with_data = 0
    total_cells_with_data = 0

    for col_idx in range(len(header)):
        col_has_data = False
        col_data_count = 0
        for row in non_empty_rows[:10]:  # Check first 10 non-empty rows
            if col_idx < len(row) and row[col_idx] and str(row[col_idx]).strip():
                col_has_data = True
                col_data_count += 1
        if col_has_data:
            cols_with_data += 1
            total_cells_with_data += col_data_count

    # If only 1-2 columns have data but header suggests many more, extraction failed
    if cols_with_data <= 2 and len(header) > 5:
        return False

    # Check if first column has all the data concatenated (Zoetis pattern)
    # This happens when pdfplumber can't detect column boundaries
    if cols_with_data == 1 and len(header) > 3:
        # Check if the single column with data has very long values
        # (which would indicate concatenated data)
        first_col_idx = 0
        for col_idx in range(len(header)):
            for row in non_empty_rows[:5]:
                if col_idx < len(row) and row[col_idx] and str(row[col_idx]).strip():
                    first_col_idx = col_idx
                    break
            if first_col_idx > 0:
                break

        avg_len = 0
        count = 0
        for row in non_empty_rows[:5]:
            if first_col_idx < len(row) and row[first_col_idx]:
                avg_len += len(str(row[first_col_idx]))
                count += 1

        if count > 0:
            avg_len = avg_len / count
            # If average cell length > 50 chars, it's likely concatenated data
            if avg_len > 50:
                return False

    return True


def detect_bom_table(pdf_path: str) -> Dict:
    """
    Detect the primary BOM table using multi-factor scoring.

    Args:
        pdf_path: Path to PDF file

    Returns:
        Dictionary with:
            - table_data: pd.DataFrame with extracted data
            - confidence: float (0-1) confidence score
            - page_numbers: List of page numbers where table was found
            - header_row: List of header column names

    Raises:
        ValueError: If no BOM table detected with sufficient confidence
    """
    candidates = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            # Extract all tables from page
            tables = page.extract_tables()

            for table_idx, table in enumerate(tables):
                if not table or len(table) < 2:  # Need header + at least 1 data row
                    continue

                # Check if table data is valid (not all crammed into one column)
                if not _is_table_data_valid(table):
                    continue

                # Score this table
                score = 0
                header_row = table[0]

                # Factor 1: Header keyword matching
                header_text = ' '.join([str(cell).lower() if cell else '' for cell in header_row])
                for keyword, weight in HEADER_KEYWORDS.items():
                    if keyword in header_text:
                        score += weight

                # Factor 2: Row count (more rows = likely BOM)
                row_count = len(table)
                score += min(row_count / 5, 10)  # Cap at 10 points

                # Factor 3: Column count (typical BOM has 4-8 columns)
                col_count = len(header_row)
                if 4 <= col_count <= 8:
                    score += 5

                # Factor 4: Numeric data presence (Qty column indicator)
                numeric_cells = sum(1 for row in table[1:] for cell in row
                                  if cell and str(cell).replace('.','').replace(',','').isdigit())
                score += min(numeric_cells / len(table), 5)

                candidates.append({
                    'table': table,
                    'score': score,
                    'page': page_num + 1,
                    'table_idx': table_idx,
                    'header': header_row
                })

    # Sort by score descending
    candidates.sort(key=lambda x: x['score'], reverse=True)

    def _has_valid_mpn_column(df):
        """Check if DataFrame has a column that can be mapped to MPN."""
        for col in df.columns:
            col_type = detect_column_type(str(col))
            if col_type == 'mpn':
                return True
        return False

    if not candidates or candidates[0]['score'] < 15:  # Minimum confidence threshold
        # Try word-position extraction first (most accurate)
        word_result = _extract_bom_by_word_positions(pdf_path)
        if word_result and len(word_result['table_data']) > 0:
            # Verify it has valid columns before accepting
            if _has_valid_mpn_column(word_result['table_data']):
                return word_result

        # Then try text-based extraction as fallback
        text_result = _extract_table_from_text(pdf_path)
        if text_result and _has_valid_mpn_column(text_result['table_data']):
            return text_result

        # Return word result anyway if it exists (let downstream handle errors)
        if word_result and len(word_result['table_data']) > 0:
            return word_result
        if text_result:
            return text_result

        raise ValueError(ERROR_MESSAGES['no_table'])

    # Even if we found tables, verify the best one has valid data distribution
    # If not, try word-position or text extraction (handles Zoetis-style PDFs
    # where table structure is detected but data is all concatenated into one column)
    if not _is_table_data_valid(candidates[0]['table']):
        # Try word-position extraction first
        word_result = _extract_bom_by_word_positions(pdf_path)
        if word_result and len(word_result['table_data']) > 0:
            if _has_valid_mpn_column(word_result['table_data']):
                return word_result

        # Then try text extraction
        text_result = _extract_table_from_text(pdf_path)
        if text_result and _has_valid_mpn_column(text_result['table_data']):
            return text_result

        # Fall through to use the table anyway if all extraction methods fail

    # Take highest-scoring table
    best_table = candidates[0]

    # Check for multi-page continuation
    # If multiple tables have similar scores and same header structure, merge them
    merged_table = best_table['table']
    pages = [best_table['page']]

    for candidate in candidates[1:]:
        # Same header structure + high score = continuation
        if (candidate['score'] >= best_table['score'] * 0.8 and
            _headers_match(best_table['header'], candidate['header'])):
            merged_table.extend(candidate['table'][1:])  # Skip duplicate header
            pages.append(candidate['page'])

    # Convert to DataFrame
    df = pd.DataFrame(merged_table[1:], columns=merged_table[0])

    return {
        'table_data': df,
        'confidence': min(best_table['score'] / 50, 1.0),  # Normalize to 0-1
        'page_numbers': pages,
        'header_row': best_table['header']
    }


def split_merged_cells(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect and fill vertically merged cells.

    Logic:
    - For each column, scan top-to-bottom
    - If cell is empty AND previous cell had value, propagate value down
    - Stop propagation when non-empty cell found
    - Special case: MPN column should NEVER be merged (indicates multi-line item)

    Args:
        df: DataFrame with potential merged cells

    Returns:
        DataFrame with merged cells split and values propagated
    """
    df = df.copy()

    for col in df.columns:
        # Skip potential MPN columns - empty MPN = multi-line description
        col_lower = str(col).lower()
        if any(keyword in col_lower for keyword in ['mpn', 'part number', 'p/n', 'part #']):
            continue

        last_value = None
        for idx in range(len(df)):
            try:
                current = df.at[idx, col]

                # Handle case where df.at returns a Series (shouldn't happen, but does sometimes)
                if isinstance(current, pd.Series):
                    current = current.iloc[0] if len(current) > 0 else None

                if pd.isna(current) or str(current).strip() == '':
                    if last_value is not None:
                        df.at[idx, col] = last_value  # Propagate
                else:
                    last_value = str(current).strip()
            except (KeyError, IndexError):
                # Skip if column doesn't exist or index out of range
                continue

    return df


def consolidate_multiline_items(df: pd.DataFrame, mpn_col: str, desc_col: str) -> pd.DataFrame:
    """
    Merge rows where MPN is empty (indicates description continuation).

    Logic:
    - Scan for rows with empty MPN
    - If previous row has MPN, this is a continuation
    - Concatenate description to previous row with newline
    - Mark row for deletion
    - Keep first row's Qty/RefDes values

    Args:
        df: DataFrame with potential multi-line items
        mpn_col: Name of MPN column
        desc_col: Name of Description column

    Returns:
        DataFrame with multi-line items consolidated
    """
    df = df.copy()
    rows_to_delete = []

    for idx in range(1, len(df)):  # Start from row 1
        try:
            current_mpn = df.at[idx, mpn_col]

            # Handle case where df.at returns a Series
            if isinstance(current_mpn, pd.Series):
                current_mpn = current_mpn.iloc[0] if len(current_mpn) > 0 else None

            if pd.isna(current_mpn) or str(current_mpn).strip() == '':
                prev_idx = idx - 1

                # Check if previous row has MPN (valid BOM item)
                prev_mpn = df.at[prev_idx, mpn_col]
                if isinstance(prev_mpn, pd.Series):
                    prev_mpn = prev_mpn.iloc[0] if len(prev_mpn) > 0 else None

                if not (pd.isna(prev_mpn) or str(prev_mpn).strip() == ''):
                    # Concatenate description
                    prev_desc_val = df.at[prev_idx, desc_col]
                    current_desc_val = df.at[idx, desc_col]

                    # Handle Series returns
                    if isinstance(prev_desc_val, pd.Series):
                        prev_desc_val = prev_desc_val.iloc[0] if len(prev_desc_val) > 0 else None
                    if isinstance(current_desc_val, pd.Series):
                        current_desc_val = current_desc_val.iloc[0] if len(current_desc_val) > 0 else None

                    prev_desc = str(prev_desc_val) if not pd.isna(prev_desc_val) else ''
                    current_desc = str(current_desc_val) if not pd.isna(current_desc_val) else ''

                    if current_desc.strip():
                        combined = f"{prev_desc}\n{current_desc}".strip() if prev_desc.strip() else current_desc
                        df.at[prev_idx, desc_col] = combined

                    rows_to_delete.append(idx)
        except (KeyError, IndexError):
            # Skip if column doesn't exist
            continue

    # Drop continuation rows
    if rows_to_delete:
        df = df.drop(rows_to_delete).reset_index(drop=True)

    return df


def remove_duplicate_headers(df: pd.DataFrame, original_header: List) -> pd.DataFrame:
    """
    Remove rows that match the original header pattern.

    Logic:
    - Compare each row to the original header
    - If >= 70% of cells match header keywords (case-insensitive), delete row

    Args:
        df: DataFrame with potential duplicate headers
        original_header: Original header row to match against

    Returns:
        DataFrame with duplicate header rows removed
    """
    header_keywords = set(str(h).lower().strip() for h in original_header if h)
    rows_to_delete = []

    for idx in range(len(df)):
        row_values = set(str(v).lower().strip() for v in df.iloc[idx] if v)

        # Calculate overlap
        overlap = len(header_keywords & row_values)
        match_ratio = overlap / len(header_keywords) if header_keywords else 0

        if match_ratio >= 0.7:  # 70% match = likely header
            rows_to_delete.append(idx)

    if rows_to_delete:
        df = df.drop(rows_to_delete).reset_index(drop=True)

    return df


def align_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure consistent column count and remove empty rows.

    Logic:
    - Fill NaN/None with empty strings
    - Remove rows where ALL cells are empty
    - Strip whitespace from all cells

    Args:
        df: DataFrame to clean

    Returns:
        Cleaned DataFrame
    """
    # Replace NaN/None with empty strings
    df = df.fillna('')

    # Remove rows where all values are empty
    df = df[~df.apply(lambda row: all(str(v).strip() == '' for v in row), axis=1)]

    # Strip whitespace from all cells
    df = df.map(lambda x: str(x).strip() if pd.notna(x) else '')

    return df.reset_index(drop=True)


def detect_column_type(col_name: str) -> Optional[str]:
    """
    Detect what type of column this is based on header name.

    Returns one of: 'item_number', 'manufacturer', 'mpn', 'customer_pn',
                    'vendor', 'vendor_pn', 'qty', 'refdes', 'description', None
    """
    col_lower = str(col_name).lower().strip()

    # Item Number detection
    if any(kw in col_lower for kw in ['item number', 'item #', 'item no', 'line number', 'line #', 'line no']):
        # But not if it's "part number" or "model number"
        if 'part' not in col_lower and 'model' not in col_lower:
            return 'item_number'

    # Manufacturer detection (name, not part number)
    if any(kw in col_lower for kw in ['manufacturer name', 'mfg name', 'mfr name']):
        return 'manufacturer'
    if col_lower in ['manufacturer', 'mfg', 'mfr', 'manufacturer:', 'mfg:', 'mfr:']:
        return 'manufacturer'

    # MPN detection (Manufacturer Part Number)
    if any(kw in col_lower for kw in ['model number', 'model no', 'model #']):
        return 'mpn'
    if any(kw in col_lower for kw in ['manufacturer part', 'manufacturer pn', 'manufacturer p/n',
                                       'mfg pn', 'mfg p/n', 'mfg part', 'mfr pn', 'mfr p/n']):
        return 'mpn'
    if any(kw in col_lower for kw in ['mpn', 'part number', 'part #', 'part no', 'p/n', 'pn']):
        # But not if it's vendor/supplier/customer part number
        if not any(kw in col_lower for kw in ['vendor', 'supplier', 'customer', 'internal', 'kjr']):
            return 'mpn'

    # Customer/Internal Part Number detection
    if any(kw in col_lower for kw in ['customer pn', 'customer p/n', 'customer part',
                                       'internal pn', 'internal p/n', 'company pn',
                                       'kjr p/n', 'kjr pn']):
        return 'customer_pn'

    # Vendor/Supplier Name detection
    if any(kw in col_lower for kw in ['vendor name', 'supplier name', 'vendor:', 'supplier:']):
        return 'vendor'
    if col_lower in ['vendor', 'supplier', 'source']:
        return 'vendor'

    # Vendor/Supplier Part Number detection
    if any(kw in col_lower for kw in ['vendor part', 'vendor pn', 'vendor p/n',
                                       'supplier part', 'supplier pn', 'supplier p/n']):
        return 'vendor_pn'

    # Quantity detection
    if any(kw in col_lower for kw in ['qty', 'quantity', 'count', 'amount', 'qty required',
                                       'qty per', 'qty/assy', 'per assy']):
        return 'qty'

    # Reference Designator detection
    if any(kw in col_lower for kw in ['ref des', 'refdes', 'ref desg', 'reference designator',
                                       'designator', 'location', 'loc', 'reference', 'ref']):
        return 'refdes'

    # Description detection
    if any(kw in col_lower for kw in ['description', 'desc', 'notes', 'comment', 'remarks',
                                       'part description', 'component description']):
        return 'description'

    return None


def map_to_bom_schema(df: pd.DataFrame, extracted_headers: List) -> pd.DataFrame:
    """
    Map extracted columns to enhanced BOM schema.

    Output Schema (all horizontal columns):
        - Item Number (if available)
        - Manufacturer (if available)
        - Manufacturer Part Number (MPN) - REQUIRED
        - Customer Part Number (if available)
        - Vendor/Supplier (if available)
        - Vendor Part Number (if available)
        - Quantity (default to "1" if not found)
        - Reference Designators (if available)
        - Description (if available)

    Args:
        df: DataFrame with extracted data
        extracted_headers: Original header names from PDF

    Returns:
        DataFrame mapped to enhanced BOM schema

    Raises:
        ValueError: If no MPN column detected
    """
    # Detect column types
    column_mapping = {}
    for col in df.columns:
        col_type = detect_column_type(col)
        if col_type:
            column_mapping[col_type] = col

    # Build standardized DataFrame with ALL required columns
    standardized = pd.DataFrame()

    # Item Number (if detected, otherwise generate)
    if 'item_number' in column_mapping:
        standardized['Item Number'] = df[column_mapping['item_number']]
    else:
        standardized['Item Number'] = range(1, len(df) + 1)

    # Manufacturer
    if 'manufacturer' in column_mapping:
        standardized['Manufacturer'] = df[column_mapping['manufacturer']]
    else:
        standardized['Manufacturer'] = ''

    # MPN (REQUIRED)
    if 'mpn' in column_mapping:
        standardized['Manufacturer Part Number (MPN)'] = df[column_mapping['mpn']]
    else:
        # Fallback: try to use the existing excel_tool column detection
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            temp_path = tmp.name
            df.to_excel(temp_path, index=False)

        try:
            _, col_map = find_header_row_and_map(temp_path)
            if col_map.get('mpn'):
                mpn_col_name = col_map['mpn']
                # Ensure the column exists in df - might be integer index
                if mpn_col_name in df.columns:
                    standardized['Manufacturer Part Number (MPN)'] = df[mpn_col_name]
                elif isinstance(mpn_col_name, int) and mpn_col_name < len(df.columns):
                    # Use positional indexing
                    standardized['Manufacturer Part Number (MPN)'] = df.iloc[:, mpn_col_name]
                else:
                    # Try to find by looking at column names
                    mpn_found = False
                    for col in df.columns:
                        if detect_column_type(str(col)) == 'mpn':
                            standardized['Manufacturer Part Number (MPN)'] = df[col]
                            mpn_found = True
                            break
                    if not mpn_found:
                        raise ValueError(ERROR_MESSAGES['no_mpn'])
            else:
                raise ValueError(ERROR_MESSAGES['no_mpn'])
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    # Customer Part Number
    if 'customer_pn' in column_mapping:
        standardized['Customer Part Number'] = df[column_mapping['customer_pn']]
    else:
        standardized['Customer Part Number'] = ''

    # Vendor/Supplier
    if 'vendor' in column_mapping:
        standardized['Vendor/Supplier'] = df[column_mapping['vendor']]
    else:
        standardized['Vendor/Supplier'] = ''

    # Vendor Part Number
    if 'vendor_pn' in column_mapping:
        standardized['Vendor Part Number'] = df[column_mapping['vendor_pn']]
    else:
        standardized['Vendor Part Number'] = ''

    # Quantity
    if 'qty' in column_mapping:
        standardized['Quantity'] = df[column_mapping['qty']]
    else:
        standardized['Quantity'] = '1'  # Default quantity

    # Reference Designators
    if 'refdes' in column_mapping:
        standardized['Reference Designators'] = df[column_mapping['refdes']]
    else:
        standardized['Reference Designators'] = ''

    # Description
    if 'description' in column_mapping:
        standardized['Description'] = df[column_mapping['description']]
    else:
        standardized['Description'] = ''

    # Clean up: remove rows with empty MPN
    standardized = standardized[standardized['Manufacturer Part Number (MPN)'].astype(str).str.strip() != '']

    return standardized


def generate_clean_excel(df: pd.DataFrame, output_path: str) -> str:
    """
    Generate Excel file with strict formatting rules.

    Requirements:
    - No merged cells
    - Consistent headers in row 1
    - Data starts at row 2
    - Auto-adjusted column widths
    - Plain text format (no formulas)

    Args:
        df: DataFrame to write to Excel
        output_path: Path where Excel file should be saved

    Returns:
        Path to generated Excel file
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"

    # Write headers (row 1)
    for col_idx, col_name in enumerate(df.columns, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.value = col_name
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=False)

    # Write data (starting row 2)
    for row_idx, row_data in enumerate(df.values, start=2):
        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.value = str(value) if pd.notna(value) else ''
            cell.alignment = Alignment(horizontal='left', vertical='top', wrap_text=True)

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter

        for cell in column:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass

        adjusted_width = min(max_length + 2, 50)  # Cap at 50 chars
        ws.column_dimensions[column_letter].width = adjusted_width

    # Verify no merged cells (should be empty set)
    assert len(ws.merged_cells.ranges) == 0, "Generated Excel contains merged cells!"

    # Save
    wb.save(output_path)
    return output_path


def extract_bom_from_pdf(pdf_path: str, output_excel_path: str) -> Dict:
    """
    Main entry point: Extract BOM from PDF and generate clean Excel file.

    Args:
        pdf_path: Path to input PDF file
        output_excel_path: Path where Excel file should be saved

    Returns:
        Dictionary with:
            - success: bool
            - excel_path: str
            - metadata: Dict with pages_processed, rows_extracted, confidence, columns_detected
            - warnings: List[str]

    Raises:
        ValueError: If PDF validation or extraction fails
    """
    warnings = []

    # Step 1: Validate digital PDF
    validate_digital_pdf(pdf_path)

    # Step 2: Detect BOM table
    table_data = detect_bom_table(pdf_path)

    if table_data['confidence'] < 0.6:
        warnings.append(f"BOM table detected with low confidence ({table_data['confidence']:.0%}). Results may require manual review.")

    # Step 3: Normalize
    df = table_data['table_data']
    df = split_merged_cells(df)

    # Try to detect MPN and Description columns for multi-line consolidation
    # Use column type detection on the header row
    mpn_col = None
    desc_col = None

    for col in df.columns:
        col_type = detect_column_type(str(col))
        if col_type == 'mpn' and mpn_col is None:
            mpn_col = col
        elif col_type == 'description' and desc_col is None:
            desc_col = col

    # If not found, use position-based fallbacks
    if mpn_col is None:
        # Look for first column with MPN-like data
        for col in df.columns:
            if df[col].astype(str).str.len().mean() < 30:  # Short strings = likely MPN
                mpn_col = col
                break
        if mpn_col is None:
            mpn_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    if desc_col is None:
        # Look for last text column (usually description)
        desc_col = df.columns[-1]

    df = consolidate_multiline_items(df, mpn_col, desc_col)

    df = remove_duplicate_headers(df, table_data['header_row'])
    df = align_and_clean(df)

    # Step 4: Map to BOM schema
    standardized_df = map_to_bom_schema(df, table_data['header_row'])

    # Step 5: Generate Excel
    generate_clean_excel(standardized_df, output_excel_path)

    return {
        'success': True,
        'excel_path': output_excel_path,
        'metadata': {
            'pages_processed': table_data['page_numbers'],
            'rows_extracted': len(standardized_df),
            'confidence': table_data['confidence'],
            'columns_detected': list(standardized_df.columns)
        },
        'warnings': warnings
    }
