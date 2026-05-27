from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
import tempfile
import os
import json
import uuid
from typing import Optional, Dict, List
import logging
from excel_tool import compare_boms, find_header_row_and_map, read_bom_with_auto_headers, compare_boms_manual
from pdf_tool import extract_bom_from_pdf
from pydantic import BaseModel
from bom_enhancements import (
    alias_store,
    audit_log,
    apply_alias_folding,
    apply_enhanced_norm_reclassify,
    enhanced_norm,
    extract_revision,
    export_with_template,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data models for manual column mapping
class ColumnMapping(BaseModel):
    mpn: Optional[str] = None
    qty: Optional[str] = None
    refdes: Optional[str] = None
    description: Optional[str] = None

class ManualComparisonRequest(BaseModel):
    file1_mapping: ColumnMapping
    file2_mapping: ColumnMapping

APP_ENV = os.getenv("APP_ENV", "development").lower()
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")

app = FastAPI(
    title="BOM Comparison API",
    description="API for comparing Bill of Materials Excel files",
    version="1.0.0"
)

# Configure CORS
if ALLOWED_ORIGINS == "*":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
else:
    origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"]
    )

@app.get("/")
async def root():
    return {"message": "BOM Comparison API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "bom-comparison-api"}

@app.post("/api/analyze-files")
async def analyze_files(
    file1: UploadFile = File(...),
    file2: UploadFile = File(...)
):
    """
    Analyze Excel files and return available columns for user selection.

    Returns:
        JSON with file columns and suggested mappings
    """
    try:
        # Validate file types
        allowed_extensions = {'.xlsx', '.xls'}
        file1_ext = os.path.splitext(file1.filename)[1].lower()
        file2_ext = os.path.splitext(file2.filename)[1].lower()

        if file1_ext not in allowed_extensions or file2_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail="Only .xlsx and .xls files are supported"
            )

        # Create temporary files
        with tempfile.NamedTemporaryFile(delete=False, suffix=file1_ext) as tmp1:
            content1 = await file1.read()
            tmp1.write(content1)
            tmp1.flush()
            tmp1_path = tmp1.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=file2_ext) as tmp2:
            content2 = await file2.read()
            tmp2.write(content2)
            tmp2.flush()
            tmp2_path = tmp2.name

        try:
            # Analyze both files
            logger.info(f"Analyzing columns for {file1.filename} and {file2.filename}")

            # Get columns and auto-detected mappings
            df1, auto_map1 = read_bom_with_auto_headers(tmp1_path)
            df2, auto_map2 = read_bom_with_auto_headers(tmp2_path)

            # Get column lists
            file1_columns = list(df1.columns)
            file2_columns = list(df2.columns)

            # Create suggested mappings based on auto-detection
            file1_suggested = {}
            file2_suggested = {}

            for key, col_name in auto_map1.items():
                file1_suggested[key] = col_name

            for key, col_name in auto_map2.items():
                file2_suggested[key] = col_name

            return JSONResponse(content={
                "file1": {
                    "filename": file1.filename,
                    "columns": file1_columns,
                    "suggested_mapping": file1_suggested
                },
                "file2": {
                    "filename": file2.filename,
                    "columns": file2_columns,
                    "suggested_mapping": file2_suggested
                }
            })

        finally:
            # Clean up temporary files
            try:
                os.unlink(tmp1_path)
                os.unlink(tmp2_path)
            except Exception as e:
                logger.warning(f"Failed to clean up temporary files: {e}")

    except Exception as e:
        import traceback
        logger.error(f"Error during file analysis: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"File analysis failed: {str(e)}"
        )

@app.post("/api/compare-manual")
async def compare_files_manual(
    file1: UploadFile = File(...),
    file2: UploadFile = File(...),
    file1_mpn: str = Form(...),
    file1_qty: str = Form(None),
    file1_refdes: str = Form(None),
    file1_description: str = Form(None),
    file2_mpn: str = Form(...),
    file2_qty: str = Form(None),
    file2_refdes: str = Form(None),
    file2_description: str = Form(None)
):
    """
    Compare two BOM Excel files using manually selected columns.

    Args:
        file1: First Excel file (original)
        file2: Second Excel file (new version)
        file1_mpn, file1_qty, etc.: Column names for file1
        file2_mpn, file2_qty, etc.: Column names for file2

    Returns:
        JSON with comparison results
    """
    try:
        # Validate file types
        allowed_extensions = {'.xlsx', '.xls'}
        file1_ext = os.path.splitext(file1.filename)[1].lower()
        file2_ext = os.path.splitext(file2.filename)[1].lower()

        if file1_ext not in allowed_extensions or file2_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail="Only .xlsx and .xls files are supported"
            )

        # Create temporary files
        with tempfile.NamedTemporaryFile(delete=False, suffix=file1_ext) as tmp1:
            content1 = await file1.read()
            tmp1.write(content1)
            tmp1.flush()
            tmp1_path = tmp1.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=file2_ext) as tmp2:
            content2 = await file2.read()
            tmp2.write(content2)
            tmp2.flush()
            tmp2_path = tmp2.name

        try:
            # Create manual column mappings
            manual_map1 = {}
            manual_map2 = {}

            if file1_mpn: manual_map1['mpn'] = file1_mpn
            if file1_qty: manual_map1['qty'] = file1_qty
            if file1_refdes: manual_map1['refdes'] = file1_refdes
            if file1_description: manual_map1['description'] = file1_description

            if file2_mpn: manual_map2['mpn'] = file2_mpn
            if file2_qty: manual_map2['qty'] = file2_qty
            if file2_refdes: manual_map2['refdes'] = file2_refdes
            if file2_description: manual_map2['description'] = file2_description

            logger.info(f"Manual comparison with mappings:")
            logger.info(f"File1: {manual_map1}")
            logger.info(f"File2: {manual_map2}")

            # Perform comparison with manual mappings
            results = compare_boms_manual(tmp1_path, tmp2_path, manual_map1, manual_map2)

            # Post-process: fold MPN aliases, reclassify formatting-only mods
            results = apply_alias_folding(results, alias_store)
            results = apply_enhanced_norm_reclassify(results)

            # Audit
            try:
                audit_log.record({
                    "kind": "compare-manual",
                    "file1": {
                        "name": file1.filename,
                        "sha256": audit_log.file_hash(tmp1_path),
                    },
                    "file2": {
                        "name": file2.filename,
                        "sha256": audit_log.file_hash(tmp2_path),
                    },
                    "mapping": {"file1": manual_map1, "file2": manual_map2},
                    "summary": results.get("summary_stats", {}),
                    "revision": {
                        "file1": extract_revision(file1.filename),
                        "file2": extract_revision(file2.filename),
                    },
                })
            except Exception as ae:
                logger.warning(f"Audit log write failed: {ae}")

            logger.info("Manual comparison completed successfully")

            return JSONResponse(content=jsonable_encoder(results))

        finally:
            # Clean up temporary files
            try:
                os.unlink(tmp1_path)
                os.unlink(tmp2_path)
            except Exception as e:
                logger.warning(f"Failed to clean up temporary files: {e}")

    except Exception as e:
        import traceback
        logger.error(f"Error during manual comparison: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Manual comparison failed: {str(e)}"
        )

@app.options("/api/compare")
async def compare_files_options():
    """Handle preflight CORS requests"""
    return {"message": "CORS preflight handled"}

@app.options("/api/analyze-files")
async def analyze_files_options():
    """Handle preflight CORS requests"""
    return {"message": "CORS preflight handled"}

@app.options("/api/compare-manual")
async def compare_manual_options():
    """Handle preflight CORS requests"""
    return {"message": "CORS preflight handled"}

@app.post("/api/compare")
async def compare_files(
    file1: UploadFile = File(...),
    file2: UploadFile = File(...)
):
    """
    Compare two BOM Excel files and return the differences.
    
    Args:
        file1: First Excel file (original)
        file2: Second Excel file (new version)
    
    Returns:
        JSON with comparison results including:
        - new_parts: Parts only in file2
        - removed_parts: Parts only in file1
        - modified_parts: Parts with BOTH QTY AND REF DES changes (MPN must be the same)
        - unchanged_parts: Parts with identical data
        - unrecognized_parts: Parts that couldn't be categorized
        - summary_stats: Statistics about the comparison
    """
    try:
        # Validate file types
        allowed_extensions = {'.xlsx', '.xls'}
        file1_ext = os.path.splitext(file1.filename)[1].lower()
        file2_ext = os.path.splitext(file2.filename)[1].lower()
        
        if file1_ext not in allowed_extensions or file2_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail="Only .xlsx and .xls files are supported"
            )
        
        # Create temporary files with proper flushing
        with tempfile.NamedTemporaryFile(delete=False, suffix=file1_ext) as tmp1:
            content1 = await file1.read()
            tmp1.write(content1)
            tmp1.flush()  # Ensure data is written to disk
            tmp1_path = tmp1.name
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=file2_ext) as tmp2:
            content2 = await file2.read()
            tmp2.write(content2)
            tmp2.flush()  # Ensure data is written to disk
            tmp2_path = tmp2.name
        
        try:
            # Perform comparison
            logger.info(f"Starting comparison of {file1.filename} and {file2.filename}")
            
            # Temporarily enable debug output to diagnose issue
            os.environ["DEBUG_VERBOSE"] = "true"
            
            results = compare_boms(tmp1_path, tmp2_path)

            # Post-process: fold MPN aliases, reclassify formatting-only mods
            results = apply_alias_folding(results, alias_store)
            results = apply_enhanced_norm_reclassify(results)

            # Audit
            try:
                audit_log.record({
                    "kind": "compare-auto",
                    "file1": {
                        "name": file1.filename,
                        "sha256": audit_log.file_hash(tmp1_path),
                    },
                    "file2": {
                        "name": file2.filename,
                        "sha256": audit_log.file_hash(tmp2_path),
                    },
                    "summary": results.get("summary_stats", {}),
                    "revision": {
                        "file1": extract_revision(file1.filename),
                        "file2": extract_revision(file2.filename),
                    },
                })
            except Exception as ae:
                logger.warning(f"Audit log write failed: {ae}")

            # Debug: Log the results before JSON encoding
            logger.info(f"Comparison completed. Removed parts count: {len(results.get('removed_parts', []))}")
            for i, part in enumerate(results.get('removed_parts', [])):
                logger.info(f"  Removed part {i+1}: {part.get('MPN', 'Unknown')}")
            
            logger.info("Comparison completed successfully")
            
            # Ensure JSON-serializable output (handles numpy types etc.)
            payload = jsonable_encoder(results)
            
            # Debug: Log after JSON encoding
            logger.info(f"After JSON encoding. Removed parts count: {len(payload.get('removed_parts', []))}")
            
            return JSONResponse(content=payload)
            
        finally:
            # Clean up temporary files
            try:
                os.unlink(tmp1_path)
                os.unlink(tmp2_path)
            except Exception as e:
                logger.warning(f"Failed to clean up temporary files: {e}")
                
    except Exception as e:
        import traceback
        logger.error(f"Error during comparison: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Comparison failed: {str(e)}"
        )

@app.post("/api/pdf-to-excel")
async def pdf_to_excel(file: UploadFile = File(...)):
    """
    Extract BOM from PDF and generate clean Excel file.

    Args:
        file: PDF file containing BOM table

    Returns:
        JSON with:
            - success: bool
            - excel_filename: str (name for download)
            - excel_url: str (temporary download path)
            - metadata: Dict with pages_processed, rows_extracted, confidence, columns_detected
            - warnings: List[str]
    """
    try:
        # Validate PDF file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="File must be PDF format"
            )

        # Create temporary PDF file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_pdf:
            content = await file.read()
            tmp_pdf.write(content)
            tmp_pdf.flush()
            pdf_path = tmp_pdf.name

        try:
            # Generate output filename
            output_filename = file.filename.replace('.pdf', '_BOM.xlsx')
            output_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}_{output_filename}")

            # Extract BOM from PDF
            logger.info(f"Processing PDF: {file.filename}")
            result = extract_bom_from_pdf(pdf_path, output_path)

            logger.info(f"Successfully extracted {result['metadata']['rows_extracted']} BOM items from PDF")

            # Read the generated Excel file and return it
            with open(output_path, 'rb') as excel_file:
                excel_content = excel_file.read()

            # Create response with Excel file
            from fastapi.responses import Response

            response = Response(
                content=excel_content,
                media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                headers={
                    'Content-Disposition': f'attachment; filename="{output_filename}"',
                    'X-Metadata-Pages': str(result['metadata']['pages_processed']),
                    'X-Metadata-Rows': str(result['metadata']['rows_extracted']),
                    'X-Metadata-Confidence': str(result['metadata']['confidence']),
                    'X-Warnings': '; '.join(result['warnings']) if result['warnings'] else ''
                }
            )

            return response

        finally:
            # Clean up temporary files
            try:
                if os.path.exists(pdf_path):
                    os.unlink(pdf_path)
                if os.path.exists(output_path):
                    os.unlink(output_path)
            except Exception as e:
                logger.warning(f"Failed to clean up temporary files: {e}")

    except ValueError as e:
        # Expected errors (validation, table detection, etc.)
        logger.error(f"PDF processing validation error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        # Unexpected errors
        import traceback
        logger.error(f"Error during PDF processing: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"PDF processing failed: {str(e)}"
        )

@app.options("/api/pdf-to-excel")
async def pdf_to_excel_options():
    """Handle preflight CORS requests"""
    return {"message": "CORS preflight handled"}

# ---------------------------------------------------------------------------
# Template-preserving export
# ---------------------------------------------------------------------------

@app.post("/api/export-as-template")
async def export_as_template(
    template_file: UploadFile = File(...),
    data_file: UploadFile = File(...),
    template_mpn: str = Form(...),
    template_qty: Optional[str] = Form(None),
    template_refdes: Optional[str] = Form(None),
    template_description: Optional[str] = Form(None),
    data_mpn: str = Form(...),
    data_qty: Optional[str] = Form(None),
    data_refdes: Optional[str] = Form(None),
    data_description: Optional[str] = Form(None),
    tint: bool = Form(True),
    diff_meta: Optional[str] = Form(None),
):
    """
    Re-render the data_file's rows inside template_file's styling.

    Preserves template_file's title block / notes above the header row,
    keeps its column order + cell styles, and overwrites the data range
    with mapped rows from data_file. Optionally tints cells based on a
    diff_meta JSON payload.
    """
    allowed = {".xlsx", ".xls"}
    t_ext = os.path.splitext(template_file.filename)[1].lower()
    d_ext = os.path.splitext(data_file.filename)[1].lower()
    if t_ext not in allowed or d_ext not in allowed:
        raise HTTPException(400, "Only .xlsx and .xls files are supported")

    with tempfile.NamedTemporaryFile(delete=False, suffix=t_ext) as tt:
        tt.write(await template_file.read())
        tt.flush()
        template_path = tt.name
    with tempfile.NamedTemporaryFile(delete=False, suffix=d_ext) as td:
        td.write(await data_file.read())
        td.flush()
        data_path = td.name

    out_fd, out_path = tempfile.mkstemp(suffix=".xlsx")
    os.close(out_fd)

    try:
        template_map = {
            "mpn": template_mpn,
            "qty": template_qty,
            "refdes": template_refdes,
            "description": template_description,
        }
        data_map = {
            "mpn": data_mpn,
            "qty": data_qty,
            "refdes": data_refdes,
            "description": data_description,
        }
        template_map = {k: v for k, v in template_map.items() if v}
        data_map = {k: v for k, v in data_map.items() if v}

        meta_dict = None
        if diff_meta:
            try:
                meta_dict = json.loads(diff_meta)
            except json.JSONDecodeError:
                meta_dict = None

        stats = export_with_template(
            template_path=template_path,
            template_filename=template_file.filename,
            template_mapping=template_map,
            data_path=data_path,
            data_filename=data_file.filename,
            data_mapping=data_map,
            out_path=out_path,
            diff_meta=meta_dict,
            tint=tint,
        )

        with open(out_path, "rb") as fh:
            content = fh.read()

        safe_template_name = os.path.splitext(template_file.filename)[0]
        out_name = f"{safe_template_name}__rewritten.xlsx"

        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{out_name}"',
                "X-Rows-Written": str(stats["rows_written"]),
                "X-Header-Row": str(stats["header_row"]),
            },
        )
    except Exception as e:
        import traceback
        logger.error(f"Template export failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"Template export failed: {e}")
    finally:
        for p in (template_path, data_path, out_path):
            try:
                if os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


@app.options("/api/export-as-template")
async def export_as_template_options():
    return {"message": "CORS preflight handled"}


# ---------------------------------------------------------------------------
# Revision detection
# ---------------------------------------------------------------------------

@app.post("/api/detect-revision")
async def detect_revision(
    file1: UploadFile = File(...),
    file2: UploadFile = File(...),
):
    """Parse 'Rev X' tokens from filenames + first ~20 rows of each workbook."""
    results = {}
    for label, upl in (("file1", file1), ("file2", file2)):
        ext = os.path.splitext(upl.filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(await upl.read())
            tmp.flush()
            path = tmp.name
        try:
            import pandas as pd
            engine = "xlrd" if ext == ".xls" else None
            try:
                if engine:
                    df_raw = pd.read_excel(path, header=None, engine=engine, nrows=20)
                else:
                    df_raw = pd.read_excel(path, header=None, nrows=20)
                rows = df_raw.values.tolist()
            except Exception:
                rows = None
            rev = extract_revision(upl.filename, rows)
            results[label] = {"filename": upl.filename, "revision": rev}
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass
    return results


@app.options("/api/detect-revision")
async def detect_revision_options():
    return {"message": "CORS preflight handled"}


# ---------------------------------------------------------------------------
# MPN alias / cross-reference dictionary
# ---------------------------------------------------------------------------

class AliasIn(BaseModel):
    mpn_a: str
    mpn_b: str
    note: Optional[str] = ""


@app.get("/api/aliases")
async def list_aliases():
    return {"pairs": alias_store.list()}


@app.post("/api/aliases")
async def add_alias(body: AliasIn):
    try:
        pair = alias_store.add(body.mpn_a, body.mpn_b, body.note or "")
        return {"ok": True, "pair": pair}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/aliases")
async def remove_alias(mpn_a: str, mpn_b: str):
    removed = alias_store.remove(mpn_a, mpn_b)
    return {"ok": removed}


@app.delete("/api/aliases/all")
async def clear_aliases():
    n = alias_store.clear()
    return {"ok": True, "removed": n}


class AliasBatchIn(BaseModel):
    pairs: List[Dict[str, str]]


@app.post("/api/aliases/import")
async def import_aliases(body: AliasBatchIn):
    added = 0
    skipped = 0
    for rec in body.pairs:
        a = (rec.get("mpn_a") or "").strip()
        b = (rec.get("mpn_b") or "").strip()
        if not a or not b or a.upper() == b.upper():
            skipped += 1
            continue
        try:
            alias_store.add(a, b, rec.get("note", ""))
            added += 1
        except Exception:
            skipped += 1
    return {"ok": True, "added": added, "skipped": skipped}


@app.options("/api/aliases")
async def aliases_options():
    return {"message": "CORS preflight handled"}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@app.get("/api/audit-log")
async def get_audit_log(limit: int = 100):
    return {"events": audit_log.list(limit=limit)}


@app.delete("/api/audit-log")
async def clear_audit_log():
    audit_log.clear()
    return {"ok": True}


@app.options("/api/audit-log")
async def audit_log_options():
    return {"message": "CORS preflight handled"}


@app.get("/api/test")
async def test_endpoint():
    """Test endpoint to verify API is working"""
    return {
        "message": "API is working",
        "timestamp": "2024-01-01T00:00:00Z",
        "version": "1.0.0"
    }

@app.get("/api/test-comparison")
async def test_comparison():
    """Test endpoint using local files to debug the issue"""
    try:
        file1_path = "test_files/motherboard BOM.xls"
        file2_path = "test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls"
        
        # Test direct comparison
        results = compare_boms(file1_path, file2_path)
        
        return {
            "message": "Direct file comparison test",
            "removed_parts_count": len(results.get('removed_parts', [])),
            "removed_parts": [part.get('MPN', 'Unknown') for part in results.get('removed_parts', [])],
            "new_parts_count": len(results.get('new_parts', [])),
            "modified_parts_count": len(results.get('modified_parts', [])),
            "unchanged_parts_count": len(results.get('unchanged_parts', []))
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0" if APP_ENV in {"production", "docker"} else "127.0.0.1"
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)