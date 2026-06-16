# PDF to Excel BOM Extraction - Test Directory

This directory is for testing the PDF-to-Excel BOM extraction feature.

## Test Instructions

### 1. Prepare Test PDFs

Place engineering drawing PDFs with BOM tables in this directory. Good test cases include:

- **Simple BOMs**: Single page, 4-6 columns, no merged cells
- **Multi-page BOMs**: BOM spanning 2+ pages with repeated headers
- **Merged cells**: Item numbers that span multiple rows
- **Multi-line descriptions**: Long descriptions split across rows
- **Complex layouts**: Multiple tables, footnotes, revision histories

### 2. Test via Web UI

1. Start the application:
   ```bash
   cd /home/tony/Compare\ Tool
   docker-compose up
   ```

2. Navigate to http://localhost:3000

3. Use the "PDF to Excel Converter" section at the top

4. Upload your test PDF and click "Convert PDF to Excel"

5. Verify the downloaded Excel file:
   - No merged cells
   - Clean headers in row 1
   - MPN column properly detected
   - Multi-line descriptions consolidated
   - Duplicate headers removed (if multi-page)

### 3. Test via API Directly

```bash
# Test with curl
curl -X POST http://localhost:8000/api/pdf-to-excel \
  -F "file=@test_pdfs/your_test_file.pdf" \
  --output output.xlsx
```

### 4. Test with Python Script

```python
import requests

# Test PDF extraction
with open('test_pdfs/your_test_file.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/api/pdf-to-excel',
        files={'file': f}
    )

if response.status_code == 200:
    # Save Excel file
    with open('output.xlsx', 'wb') as out:
        out.write(response.content)

    # Check metadata headers
    print(f"Pages: {response.headers.get('X-Metadata-Pages')}")
    print(f"Rows: {response.headers.get('X-Metadata-Rows')}")
    print(f"Confidence: {response.headers.get('X-Metadata-Confidence')}")
    print(f"Warnings: {response.headers.get('X-Warnings')}")
else:
    print(f"Error: {response.text}")
```

## Expected Test Scenarios

### ✅ Should Succeed

- **Digital PDFs** with selectable text
- **BOM tables** with Part Number/MPN column
- **Multi-page BOMs** with consistent headers
- **Merged cells** in non-MPN columns (Item #, etc.)
- **Multi-line descriptions** continuing on next row

### ❌ Should Fail Gracefully

- **Scanned PDFs** (image-only, no text layer)
  - Error: "This PDF appears to be a scanned document..."

- **No BOM table** (text-only PDFs)
  - Error: "Could not detect a BOM table in this PDF..."

- **Missing MPN column**
  - Error: "No part number column found..."

- **Encrypted PDFs**
  - Error: "Password-protected PDFs are not supported..."

## Edge Cases to Test

1. **Vertical merged cells**: Item # "1" spanning rows 2-5
2. **Horizontal merged cells**: Description spanning 2 columns
3. **Multi-line continuations**: Empty MPN cell with description text
4. **Repeated headers**: Header row on each page
5. **Footnotes in table**: Notes/comments mixed with data rows
6. **Inconsistent columns**: Different column count per page
7. **Empty rows**: Blank rows between BOM items
8. **Special characters**: Unicode, symbols in MPN/Description
9. **Large PDFs**: 50+ page documents
10. **Multiple tables**: Page has both BOM and revision table

## Validation Checklist

After extraction, verify the Excel file:

- [ ] No merged cells (can be verified with Excel or openpyxl)
- [ ] Headers in row 1 exactly
- [ ] Data starts at row 2
- [ ] Column order: Line Number, MPN, Ref Des/LOC, Qty, Description
- [ ] All MPN values present (no empty MPNs)
- [ ] Multi-line descriptions joined with newlines
- [ ] No duplicate header rows
- [ ] Column widths auto-adjusted
- [ ] File can be immediately uploaded to BOM Comparison tool

## Creating Test PDFs

If you need to create test PDFs programmatically:

```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors

# Create test BOM table
data = [
    ['Item', 'MPN', 'Description', 'Qty', 'Ref Des'],
    ['1', 'RES-001', 'Resistor 10k 0603', '100', 'R1-R100'],
    ['2', 'CAP-002', 'Capacitor 100nF', '50', 'C1-C50'],
    # ... more rows
]

doc = SimpleDocTemplate('test_bom.pdf', pagesize=letter)
table = Table(data)
table.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
    ('GRID', (0, 0), (-1, -1), 1, colors.black)
]))

doc.build([table])
```

## Debugging Failed Extractions

If extraction fails, check:

1. **PDF text layer**: Open PDF, try to select text with cursor
   - If text can't be selected → scanned PDF (not supported)

2. **Table structure**: Look for visible table borders/grid
   - If no table → detection will fail

3. **Column headers**: Look for keywords like "MPN", "Part Number", "Qty"
   - If no keywords → may detect wrong table

4. **Backend logs**:
   ```bash
   docker logs compare-tool-backend-1
   ```

## Performance Benchmarks

Expected processing time:

- **1-5 pages**: < 5 seconds
- **10-20 pages**: < 15 seconds
- **50+ pages**: < 60 seconds

If processing takes longer, check for:
- Very large PDF file size (> 50MB)
- Complex graphics/images embedded
- Unusual PDF encoding

## Support

If you encounter issues:

1. Check backend logs for detailed error messages
2. Verify PDF meets requirements (digital, has text layer, has table)
3. Try simplifying the PDF (remove non-BOM pages)
4. Report issues with anonymized sample PDF
