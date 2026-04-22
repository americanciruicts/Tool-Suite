'use client';

import { useState, useCallback, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, FileSpreadsheet, ArrowLeftRight, CheckCircle, XCircle, AlertCircle, HelpCircle, ChevronDown, ChevronUp, Search, Printer, FileDown } from 'lucide-react';
import axios from 'axios';
// Removed unused import

interface BOMPart {
  MPN: string;
  'Ref Des/LOC': string;
  Qty: string;
  Description: string;
  'Line Number': string;
}

interface ModifiedPart {
  MPN: string;
  'File1 Ref Des': string;
  'File2 Ref Des': string;
  'File1 Qty': string;
  'File2 Qty': string;
  'File1 Description': string;
  'File2 Description': string;
  'File1 Line': string;
  'File2 Line': string;
  diffs?: {
    Qty?: boolean;
    Description?: boolean;
    RefDes?: boolean;
    Line?: boolean;
  };
}

interface FileAnalysis {
  filename: string;
  columns: string[];
  suggested_mapping: {
    mpn?: string;
    qty?: string;
    refdes?: string;
    description?: string;
  };
}

interface AnalysisResults {
  file1: FileAnalysis;
  file2: FileAnalysis;
}

interface ComparisonResults {
  new_parts: BOMPart[];
  removed_parts: BOMPart[];
  modified_parts: ModifiedPart[];
  unchanged_parts: BOMPart[];
  unrecognized_parts: BOMPart[];
  summary_stats: {
    total_parts_file1: number;
    total_parts_file2: number;
    new_parts_count: number;
    removed_parts_count: number;
    modified_parts_count: number;
    unchanged_parts_count: number;
    unrecognized_parts_count: number;
  };
}

// Detect base path for API calls (handles /bom/ tunnel prefix)
function getApiBasePath(): string {
  if (typeof window === 'undefined') return '/api';
  const path = window.location.pathname;
  // If accessed via /bom/ prefix (tunnel proxy), use /bom/api
  if (path.startsWith('/bom')) return '/bom/api';
  return '/api';
}

export default function Home() {
  const [file1, setFile1] = useState<File | null>(null);
  const [file2, setFile2] = useState<File | null>(null);
  const [fileName1, setFileName1] = useState<string>('');
  const [fileName2, setFileName2] = useState<string>('');
  const [results, setResults] = useState<ComparisonResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['category-1', 'category-2', 'category-3']));
  const [prePrintExpanded, setPrePrintExpanded] = useState<Set<string> | null>(null);

  // New states for column selection
  const [analysisResults, setAnalysisResults] = useState<AnalysisResults | null>(null);
  const [showColumnSelection, setShowColumnSelection] = useState(false);
  const [selectedColumns, setSelectedColumns] = useState({
    file1: { mpn: '', qty: '', refdes: '', description: '' },
    file2: { mpn: '', qty: '', refdes: '', description: '' }
  });
  const [analyzing, setAnalyzing] = useState(false);

  // Tab state
  const [activeTab, setActiveTab] = useState<'pdf' | 'compare'>('pdf');

  // PDF to Excel conversion states
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfProcessing, setPdfProcessing] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfSuccess, setPdfSuccess] = useState<string | null>(null);
  // Validate Excel file by extension (MIME types are unreliable across OS/browsers)
  const isExcelFile = (file: File) => {
    const name = file.name.toLowerCase();
    return name.endsWith('.xlsx') || name.endsWith('.xls');
  };

  const onDrop1 = useCallback((acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (file && isExcelFile(file)) {
      setFile1(file);
      setFileName1(file.name);
    } else if (file) {
      setError('Please upload an Excel file (.xlsx or .xls)');
    }
  }, []);

  const onDrop2 = useCallback((acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (file && isExcelFile(file)) {
      setFile2(file);
      setFileName2(file.name);
      setError(null);
    } else if (file) {
      setError('Please upload an Excel file (.xlsx or .xls)');
    }
  }, []);

  const { getRootProps: getRootProps1, getInputProps: getInputProps1, isDragActive: isDragActive1 } = useDropzone({
    onDrop: onDrop1,
    multiple: false,
  });

  const { getRootProps: getRootProps2, getInputProps: getInputProps2, isDragActive: isDragActive2 } = useDropzone({
    onDrop: onDrop2,
    multiple: false,
  });

  // PDF dropzone
  const onDropPdf = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setPdfFile(acceptedFiles[0]);
      setPdfError(null);
      setPdfSuccess(null);
    }
  }, []);

  const { getRootProps: getRootPropsPdf, getInputProps: getInputPropsPdf, isDragActive: isDragActivePdf } = useDropzone({
    onDrop: onDropPdf,
    accept: {
      'application/pdf': ['.pdf'],
    },
    multiple: false,
  });

  const handlePdfUpload = async () => {
    if (!pdfFile) {
      setPdfError('Please select a PDF file first.');
      return;
    }

    setPdfProcessing(true);
    setPdfError(null);
    setPdfSuccess(null);

    try {
      const formData = new FormData();
      formData.append('file', pdfFile);

      const apiUrl = `${getApiBasePath()}/pdf-to-excel`;

      const response = await axios.post(apiUrl, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'ngrok-skip-browser-warning': 'true',
        },
        responseType: 'blob', // Important for file download
      });

      // Extract metadata from headers
      const pages = response.headers['x-metadata-pages'];
      const rows = response.headers['x-metadata-rows'];
      const confidence = response.headers['x-metadata-confidence'];
      const warnings = response.headers['x-warnings'];

      // Create download link
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = pdfFile.name.replace('.pdf', '_BOM.xlsx');
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      // Show success message
      let successMsg = `Successfully extracted ${rows || '?'} BOM items`;
      if (pages) successMsg += ` from page(s) ${pages}`;
      if (confidence) successMsg += ` with ${(parseFloat(confidence) * 100).toFixed(0)}% confidence`;
      if (warnings) successMsg += `\n\nWarnings: ${warnings}`;

      setPdfSuccess(successMsg);
      setPdfFile(null); // Clear file after success

    } catch (err: any) {
      console.error('PDF processing error:', err);
      if (err.response?.data) {
        // Try to parse error message from blob
        const reader = new FileReader();
        reader.onload = () => {
          try {
            const errorData = JSON.parse(reader.result as string);
            setPdfError(errorData.detail || 'PDF processing failed');
          } catch {
            setPdfError('PDF processing failed. Please ensure the PDF contains a valid BOM table.');
          }
        };
        reader.readAsText(err.response.data);
      } else {
        setPdfError(err.message || 'PDF processing failed. Please try again.');
      }
    } finally {
      setPdfProcessing(false);
    }
  };

  const handleAnalyzeFiles = async () => {
    if (!file1 || !file2) {
      setError('Please select both files first.');
      return;
    }

    setAnalyzing(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file1', file1);
      formData.append('file2', file2);

      const apiUrl = `${getApiBasePath()}/analyze-files`;

      const response = await axios.post(apiUrl, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'ngrok-skip-browser-warning': 'true',
        },
        timeout: 120000,
        withCredentials: false,
      });

      console.log('Analysis Response:', response.data);
      setAnalysisResults(response.data);

      // Set suggested mappings as default selections
      setSelectedColumns({
        file1: {
          mpn: response.data.file1.suggested_mapping?.mpn || '',
          qty: response.data.file1.suggested_mapping?.qty || '',
          refdes: response.data.file1.suggested_mapping?.refdes || '',
          description: response.data.file1.suggested_mapping?.description || ''
        },
        file2: {
          mpn: response.data.file2.suggested_mapping?.mpn || '',
          qty: response.data.file2.suggested_mapping?.qty || '',
          refdes: response.data.file2.suggested_mapping?.refdes || '',
          description: response.data.file2.suggested_mapping?.description || ''
        }
      });

      setShowColumnSelection(true);
    } catch (err: any) {
      console.error('Analysis error:', err);
      let errorMessage = 'File analysis failed. Please try again.';

      if (err.response?.data?.detail) {
        errorMessage = err.response.data.detail;
      }

      setError(errorMessage);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleCompare = async () => {
    if (!file1 || !file2 || !analysisResults) {
      setError('Please analyze files first.');
      return;
    }

    // Validate required MPN columns
    if (!selectedColumns.file1.mpn || !selectedColumns.file2.mpn) {
      setError('MPN column is required for both files.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file1', file1);
      formData.append('file2', file2);
      formData.append('file1_mpn', selectedColumns.file1.mpn);
      formData.append('file1_qty', selectedColumns.file1.qty);
      formData.append('file1_refdes', selectedColumns.file1.refdes);
      formData.append('file1_description', selectedColumns.file1.description);
      formData.append('file2_mpn', selectedColumns.file2.mpn);
      formData.append('file2_qty', selectedColumns.file2.qty);
      formData.append('file2_refdes', selectedColumns.file2.refdes);
      formData.append('file2_description', selectedColumns.file2.description);

      const apiUrl = `${getApiBasePath()}/compare-manual`;

      const response = await axios.post(apiUrl, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'ngrok-skip-browser-warning': 'true',
        },
        timeout: 120000,
        withCredentials: false,
      });

      console.log('Comparison Response:', response.data);
      setResults(response.data);
    } catch (err: any) {
      console.error('Comparison error:', err);
      let errorMessage = 'Comparison failed. Please try again.';

      if (err.response?.data?.detail) {
        errorMessage = err.response.data.detail;
      }

      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  const toggleCategory = (categoryId: string) => {
    const newExpanded = new Set(expandedCategories);
    if (newExpanded.has(categoryId)) {
      newExpanded.delete(categoryId);
    } else {
      newExpanded.add(categoryId);
    }
    setExpandedCategories(newExpanded);
  };

  const clearFiles = () => {
    setFile1(null);
    setFile2(null);
    setFileName1('');
    setFileName2('');
    setResults(null);
    setError(null);
    setSearchTerm('');
    setAnalysisResults(null);
    setShowColumnSelection(false);
    setSelectedColumns({
      file1: { mpn: '', qty: '', refdes: '', description: '' },
      file2: { mpn: '', qty: '', refdes: '', description: '' }
    });
  };

  const handlePrint = () => {
    if (typeof window === 'undefined') return;
    // Ensure categories are expanded for print
    setPrePrintExpanded(new Set(expandedCategories));
    setExpandedCategories(new Set(['category-1', 'category-2', 'category-3']));
    setTimeout(() => window.print(), 300);
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const restore = () => {
      if (prePrintExpanded) {
        setExpandedCategories(prePrintExpanded);
      }
    };
    window.addEventListener('afterprint', restore);
    return () => window.removeEventListener('afterprint', restore);
  }, [prePrintExpanded]);

  const exportToExcel = () => {
    if (!results) return;
    try {
      // Use exceljs for styled export that mirrors UI
      // @ts-ignore - exceljs types may not be available in the runtime image
      import('exceljs').then(async (ExcelJSImport) => {
        const ExcelJS: any = (ExcelJSImport as any).default || ExcelJSImport;
        const workbook = new ExcelJS.Workbook();

        const addStyledSheet = (name: string, headerLeft: string, headerRight: string, rows: Array<any[]>) => {
          const sheet = workbook.addWorksheet(name);
          sheet.views = [{ state: 'frozen', ySplit: 2 }];

          // Column widths to reflect UI
          sheet.columns = [
            { width: 28 }, // MPN
            { width: 24 }, // RefDes F1
            { width: 10 }, // Qty F1
            { width: 24 }, // RefDes F2
            { width: 10 }, // Qty F2
          ];

          const headerRow1 = sheet.addRow(['MPN', headerLeft, null, headerRight, null]);
          headerRow1.font = { bold: true };
          headerRow1.getCell(2).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'DBEAFE' } }; // blue-100
          headerRow1.getCell(4).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'DCFCE7' } }; // green-100
          sheet.mergeCells(1, 2, 1, 3);
          sheet.mergeCells(1, 4, 1, 5);

          const headerRow2 = sheet.addRow(['MPN', 'Ref Des (F1)', 'Qty (F1)', 'Ref Des (F2)', 'Qty (F2)']);
          headerRow2.font = { bold: true };

          // Borders for header rows
          [headerRow1, headerRow2].forEach((r: any) => r.eachCell((c: any) => {
            c.border = { top: { style: 'thin' }, left: { style: 'thin' }, bottom: { style: 'thin' }, right: { style: 'thin' } };
          }));

          // Data rows mirroring UI
          rows.forEach((a: any[]) => {
            const row: any = sheet.addRow(a);
            row.eachCell((c: any) => {
              c.border = { top: { style: 'thin' }, left: { style: 'thin' }, bottom: { style: 'thin' }, right: { style: 'thin' } };
              c.alignment = { wrapText: true };
            });
          });
        };

        // Build rows for each section from current UI state
        const changeRows = results.modified_parts
          .sort((a, b) => a.MPN.localeCompare(b.MPN))
          .map(p => [p.MPN, p['File1 Ref Des'], p['File1 Qty'], p['File2 Ref Des'], p['File2 Qty']]);
        addStyledSheet('Change', `File 1: ${fileName1 || 'File 1'}`, `File 2: ${fileName2 || 'File 2'}`, changeRows);

        const deleteRows = results.removed_parts.map(p => [p.MPN, p['Ref Des/LOC'], p.Qty, '', '']);
        addStyledSheet('Delete (File1 only)', `File 1: ${fileName1 || 'File 1'}`, `File 2: ${fileName2 || 'File 2'}`, deleteRows);

        const addRows = results.new_parts.map(p => [p.MPN, '', '', p['Ref Des/LOC'], p.Qty]);
        addStyledSheet('Add (File2 only)', `File 1: ${fileName1 || 'File 1'}`, `File 2: ${fileName2 || 'File 2'}`, addRows);

        const fileNameSafe1 = (fileName1 || 'File1').replace(/[^\w\-\.]+/g, '_');
        const fileNameSafe2 = (fileName2 || 'File2').replace(/[^\w\-\.]+/g, '_');
        const outName = `bom_comparison_${fileNameSafe1}_vs_${fileNameSafe2}.xlsx`;

        const buf = await workbook.xlsx.writeBuffer();
        const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = outName;
        link.click();
        URL.revokeObjectURL(link.href);
      });
    } catch (e) {
      console.error('Excel export failed', e);
    }
  };

  // Filter results based on search term
  const filterResults = (results: ComparisonResults, searchTerm: string) => {
    if (!searchTerm.trim()) return results;
    
    const searchLower = searchTerm.toLowerCase();
    
    const filterParts = (parts: BOMPart[]) => 
      parts.filter(part => 
        part.MPN.toLowerCase().includes(searchLower) ||
        part['Ref Des/LOC'].toLowerCase().includes(searchLower)
      );
    
    const filterModifiedParts = (parts: ModifiedPart[]) =>
      parts.filter(part =>
        part.MPN.toLowerCase().includes(searchLower) ||
        part['File1 Ref Des'].toLowerCase().includes(searchLower)
      );
    
    return {
      ...results,
      new_parts: filterParts(results.new_parts),
      removed_parts: filterParts(results.removed_parts),
      modified_parts: filterModifiedParts(results.modified_parts),
      unchanged_parts: filterParts(results.unchanged_parts),
      unrecognized_parts: filterParts(results.unrecognized_parts),
      summary_stats: {
        ...results.summary_stats,
        new_parts_count: filterParts(results.new_parts).length,
        removed_parts_count: filterParts(results.removed_parts).length,
        modified_parts_count: filterModifiedParts(results.modified_parts).length,
        unchanged_parts_count: filterParts(results.unchanged_parts).length,
        unrecognized_parts_count: filterParts(results.unrecognized_parts).length,
      }
    };
  };

  const renderPartTable = (parts: BOMPart[] | ModifiedPart[], isModified = false) => (
    <div className="overflow-x-auto">
      <table className="w-full bg-white border-2 border-gray-600 rounded-lg text-sm min-w-full border-collapse">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-2 py-2 text-left font-semibold text-sm min-w-40 border border-gray-600">MPN</th>
            <th className="px-2 py-2 text-left font-semibold text-sm min-w-24 border border-gray-600">{isModified ? 'File1 Ref Des' : 'Ref Des/LOC'}</th>
            <th className="px-2 py-2 text-left font-semibold text-sm min-w-16 border border-gray-600">{isModified ? 'File1 Qty' : 'Qty'}</th>
          </tr>
        </thead>
        <tbody>
          {parts.map((part, index) => (
            <tr key={index}>
              <td className="px-2 py-2 font-medium text-primary-600 text-sm break-all min-w-40 border border-gray-600">{part.MPN}</td>
              <td className="px-2 py-2 text-sm break-all min-w-24 border border-gray-600">{isModified ? (part as ModifiedPart)['File1 Ref Des'] : (part as BOMPart)['Ref Des/LOC']}</td>
              <td className="px-2 py-2 text-sm min-w-16 border border-gray-600">{isModified ? (part as ModifiedPart)['File1 Qty'] : (part as BOMPart).Qty}</td>
                {/* Description and Line removed */}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderEmptyTable = (message: string) => (
    <div className="overflow-x-auto">
      <table className="w-full bg-white border-2 border-gray-600 rounded-lg text-sm min-w-full border-collapse">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-2 py-2 text-left font-semibold text-sm min-w-40 border border-gray-600">MPN</th>
            <th className="px-2 py-2 text-left font-semibold text-sm min-w-24 border border-gray-600">Ref Des/LOC</th>
            <th className="px-2 py-2 text-left font-semibold text-sm min-w-16 border border-gray-600">Qty</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan={3} className="px-2 py-8 text-center text-gray-500 border border-gray-600">
              {message}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );

  const FileHeader = ({ fileName, color, position }: { fileName: string; color: string; position: 'left' | 'right' }) => (
    <div className={`flex items-center gap-2 mb-3 ${position === 'right' ? 'justify-end' : ''}`}>
      <div className={`px-3 py-1 rounded-t-lg ${color} text-white text-sm font-medium`}>
        {fileName || `File ${position === 'left' ? '1' : '2'}`}
      </div>
    </div>
  );

  const renderPartComparisonView = (results: ComparisonResults) => (
    <div className="space-y-6 category-section">
      {/* Print-only Category 1 - bypasses CategorySection wrapper */}
      <div className="hidden print:block border border-gray-200 rounded-lg overflow-hidden">
        <div className="bg-primary-600 text-white p-4">
          <h3 className="font-semibold">Category 1: Delete (Parts only in File 1) - {results.summary_stats.removed_parts_count} items</h3>
        </div>
        <div className="p-4 bg-gray-50">
          <FileHeader fileName={fileName1} color="bg-blue-600" position="left" />
          {results.removed_parts.length > 0 ? (
            renderPartTable(results.removed_parts)
          ) : (
            renderEmptyTable("No parts found in File 1 only")
          )}
        </div>
      </div>

      {/* Category 1: Delete (screen only) */}
      <div className="print:hidden">
        <CategorySection
            id="category-1"
            title="Category 1: Delete (Parts only in File 1)"
            icon={XCircle}
            color="primary"
            count={results.summary_stats.removed_parts_count}
            isExpanded={expandedCategories.has('category-1')}
            onToggle={() => toggleCategory('category-1')}
          >
          {/* Screen: Grid layout, Print: Single column */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 print:hidden">
            <div>
              <FileHeader fileName={fileName1} color="bg-blue-600" position="left" />
              {results.removed_parts.length > 0 ? (
                renderPartTable(results.removed_parts)
              ) : (
                renderEmptyTable("No parts found in File 1 only")
              )}
            </div>
            <div>
              <FileHeader fileName={fileName2} color="bg-red-600" position="right" />
              {renderEmptyTable("Not Found in File 2")}
            </div>
          </div>
          {/* Print only: Simple single column */}
          <div className="hidden print:block">
            <FileHeader fileName={fileName1} color="bg-blue-600" position="left" />
            {results.removed_parts.length > 0 ? (
              renderPartTable(results.removed_parts)
            ) : (
              renderEmptyTable("No parts found in File 1 only")
            )}
          </div>
        </CategorySection>
      </div>

      {/* Category 2: Add (Parts Only in File 2) */}
      <CategorySection
        id="category-2"
        title="Category 2: Add (Parts Only in File 2)"
        icon={CheckCircle}
        color="success"
        count={results.summary_stats.new_parts_count}
        isExpanded={expandedCategories.has('category-2')}
        onToggle={() => toggleCategory('category-2')}
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className={'print:hidden'}>
            <FileHeader fileName={fileName1} color="bg-blue-600" position="left" />
            {renderEmptyTable("Not Found in File 1")}
          </div>
          <div>
            <FileHeader fileName={fileName2} color="bg-green-600" position="right" />
            {results.new_parts.length > 0 ? (
              renderPartTable(results.new_parts)
            ) : (
              renderEmptyTable("No parts found in File 2 only")
            )}
          </div>
        </div>
      </CategorySection>

      {/* Category 3: Change (Parts with ANY Differences) */}
      <CategorySection
        id="category-3"
        title="Category 3: Change (Parts with Any Differences)"
        icon={AlertCircle}
        color="warning"
        count={results.summary_stats.modified_parts_count}
        isExpanded={expandedCategories.has('category-3')}
        onToggle={() => toggleCategory('category-3')}
      >
        {/* Category 3 content */}
        {results.modified_parts.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <div className="text-xs text-gray-600 mb-2">
              <strong>Red highlighting</strong> shows exactly what changed between files.
              <span className="text-red-600 font-semibold">CHANGED FROM</span> (File 1) →
              <span className="text-red-600 font-semibold">CHANGED TO</span> (File 2).
              Parts with ANY changes (quantity, reference designator, or description) are shown here.
            </div>
        <table className="w-full bg-white border-2 border-gray-600 rounded-lg text-sm min-w-full border-collapse">
              <thead>
                <tr>
                  <th rowSpan={2} className="px-2 py-2 text-left font-semibold text-sm min-w-40 sticky left-0 z-20 bg-gray-50">MPN</th>
                  <th colSpan={2} className="px-2 py-2 text-center font-semibold text-sm bg-blue-100 text-blue-900">File 1: {fileName1 || 'File 1'}</th>
                  <th colSpan={2} className="px-2 py-2 text-center font-semibold text-sm bg-green-100 text-green-900 border-l-4 border-gray-300">File 2: {fileName2 || 'File 2'}</th>
                </tr>
                <tr className="bg-gray-50">
                  <th className="px-2 py-2 text-left font-medium text-sm min-w-24 border border-gray-600">Ref Des (F1)</th>
                  <th className="px-2 py-2 text-left font-medium text-sm min-w-16 border border-gray-600">Qty (F1)</th>
                  <th className="px-2 py-2 text-left font-medium text-sm min-w-24 border-l-4 border-gray-800 border-t border-b border-r border-gray-700">Ref Des (F2)</th>
                  <th className="px-2 py-2 text-left font-medium text-sm min-w-16 border border-gray-600">Qty (F2)</th>
                </tr>
              </thead>
              <tbody>
                {[...results.modified_parts].sort((a, b) => a.MPN.localeCompare(b.MPN)).map((part, index) => {
                  // Helpers to ignore formatting-only differences
                  const normalizeQty = (v: any) => {
                    if (v === undefined || v === null) return '';
                    const s = String(v).trim();
                    if (!s || ['na', 'n/a', 'none'].includes(s.toLowerCase())) return '';
                    const n = Number(s);
                    if (!isNaN(n)) {
                      if (Number.isInteger(n)) return String(n);
                      const t = String(n);
                      return t.includes('.') ? t.replace(/\.0+$/, '').replace(/(\..*?)0+$/, '$1').replace(/\.$/, '') : t;
                    }
                    return s;
                  };
                  const parseRefSet = (s: any) => {
                    if (s === undefined || s === null) return new Set<string>();
                    const text = String(s).toUpperCase();
                    if (!text || ['NA', 'N/A', 'NONE', 'NULL', 'UNDEFINED'].includes(text)) return new Set<string>();
                    return new Set(text.split(/[,;\s]+/).filter(x => x.length > 0));
                  };
                  const setsEqual = (a: Set<string>, b: Set<string>) => {
                    if (a.size !== b.size) return false;
                    const arr = Array.from(a);
                    for (let i = 0; i < arr.length; i++) {
                      if (!b.has(arr[i])) return false;
                    }
                    return true;
                  };

                  const qtyDiff = normalizeQty(part['File1 Qty']) !== normalizeQty(part['File2 Qty']);
                  const refDesDiff = !setsEqual(parseRefSet(part['File1 Ref Des']), parseRefSet(part['File2 Ref Des']));

                  // Make differences more visually obvious like the manual comparison
                  const diffStyle = 'bg-red-200 border-2 border-red-500 font-bold text-red-900';
                  const unchangedBlueStyle = 'bg-blue-50 border border-gray-300';
                  const unchangedGreenStyle = 'bg-green-50 border border-gray-300';

                  return (
                    <tr key={index} className="hover:bg-gray-50">
                      <td className="px-2 py-2 font-medium text-primary-600 text-sm break-all min-w-40 sticky left-0 z-10 bg-white border border-gray-700">{part.MPN}</td>

                      {/* File 1 Ref Des - highlight if different */}
                      <td className={`px-2 py-2 text-sm break-all min-w-24 ${refDesDiff ? diffStyle : unchangedBlueStyle}`}>
                        {refDesDiff && <div className="text-xs text-red-600 font-semibold mb-1">CHANGED FROM:</div>}
                        <div className={refDesDiff ? 'p-1 rounded' : ''}>{part['File1 Ref Des']}</div>
                      </td>

                      {/* File 1 Qty - highlight if different */}
                      <td className={`px-2 py-2 text-sm min-w-16 ${qtyDiff ? diffStyle : unchangedBlueStyle}`}>
                        {qtyDiff && <div className="text-xs text-red-600 font-semibold mb-1">CHANGED FROM:</div>}
                        <div className={qtyDiff ? 'p-1 rounded' : ''}>{part['File1 Qty']}</div>
                      </td>

                      {/* File 2 Ref Des - highlight if different */}
                      <td className={`px-2 py-2 text-sm break-all min-w-24 border-l-4 border-gray-800 ${refDesDiff ? diffStyle : unchangedGreenStyle}`}>
                        {refDesDiff && <div className="text-xs text-red-600 font-semibold mb-1">CHANGED TO:</div>}
                        <div className={refDesDiff ? 'p-1 rounded' : ''}>{part['File2 Ref Des']}</div>
                      </td>

                      {/* File 2 Qty - highlight if different */}
                      <td className={`px-2 py-2 text-sm min-w-16 ${qtyDiff ? diffStyle : unchangedGreenStyle}`}>
                        {qtyDiff && <div className="text-xs text-red-600 font-semibold mb-1">CHANGED TO:</div>}
                        <div className={qtyDiff ? 'p-1 rounded' : ''}>{part['File2 Qty']}</div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
        )}
      </CategorySection>
    </div>
  );

  return (
    <div className="container mx-auto px-4 py-8 max-w-7xl">
      <div className="text-center mb-6 print:hidden">
        <h1 className="text-4xl font-bold text-gray-900 mb-2 flex items-center justify-center gap-3">
          <FileSpreadsheet className="w-8 h-8 text-primary-600" />
          BOM Tool Suite
        </h1>
        <p className="text-gray-600 text-lg">
          Convert PDF BOMs to Excel or compare two Excel BOMs
        </p>
      </div>

      {/* Tab Switcher */}
      <div className="print:hidden mb-8">
        <div className="relative flex bg-gray-200 rounded-xl p-1 max-w-md mx-auto">
          {/* Sliding background indicator */}
          <div
            className={`absolute top-1 bottom-1 w-[calc(50%-4px)] bg-white rounded-lg shadow-md transition-all duration-300 ease-in-out ${
              activeTab === 'compare' ? 'left-[calc(50%+2px)]' : 'left-1'
            }`}
          />
          <button
            onClick={() => setActiveTab('pdf')}
            className={`relative z-10 flex-1 flex items-center justify-center gap-2 py-3 px-4 rounded-lg text-sm font-semibold transition-colors duration-300 ${
              activeTab === 'pdf' ? 'text-primary-700' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
            </svg>
            PDF to Excel
          </button>
          <button
            onClick={() => setActiveTab('compare')}
            className={`relative z-10 flex-1 flex items-center justify-center gap-2 py-3 px-4 rounded-lg text-sm font-semibold transition-colors duration-300 ${
              activeTab === 'compare' ? 'text-primary-700' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <ArrowLeftRight className="w-5 h-5" />
            BOM Comparison
          </button>
        </div>
      </div>

      {/* ===== TAB 1: PDF to Excel Converter ===== */}
      {activeTab === 'pdf' && (
        <div className="print:hidden">
          <div className="max-w-2xl mx-auto">
            <div className="p-6 bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg border border-blue-200">
              <p className="text-center text-gray-600 mb-6">
                Upload engineering drawing PDFs to automatically extract BOM tables as clean Excel files
              </p>

              <div
                {...getRootPropsPdf()}
                className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all duration-200 mb-4 ${
                  isDragActivePdf
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-blue-300 hover:border-blue-400 hover:bg-blue-50 bg-white'
                }`}
              >
                <input {...getInputPropsPdf()} />
                <svg className="w-12 h-12 text-blue-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <p className="text-lg font-medium text-gray-700 mb-2">
                  {isDragActivePdf ? 'Drop PDF here' : 'Drag & drop PDF file here'}
                </p>
                <p className="text-gray-500 mb-2">or click to browse</p>
                <p className="text-xs text-gray-400">Digitally generated PDFs only (not scanned images)</p>
                {pdfFile && (
                  <div className="mt-4 p-3 bg-blue-100 rounded-lg inline-block">
                    <div className="flex items-center gap-2">
                      <svg className="w-5 h-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
                      </svg>
                      <div>
                        <p className="font-medium text-blue-900">{pdfFile.name}</p>
                        <p className="text-sm text-blue-700">
                          {(pdfFile.size / 1024).toFixed(1)} KB
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="text-center">
                <button
                  onClick={handlePdfUpload}
                  disabled={!pdfFile || pdfProcessing}
                  className={`btn-primary flex items-center gap-2 mx-auto ${
                    (!pdfFile || pdfProcessing) ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  {pdfProcessing ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                      Extracting BOM...
                    </>
                  ) : (
                    <>
                      <FileDown className="w-5 h-5" />
                      Convert PDF to Excel
                    </>
                  )}
                </button>
              </div>

              {pdfError && (
                <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                  <div className="flex items-start gap-2">
                    <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-red-800">Error</p>
                      <p className="text-sm text-red-700 whitespace-pre-line">{pdfError}</p>
                    </div>
                  </div>
                </div>
              )}

              {pdfSuccess && (
                <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
                  <div className="flex items-start gap-2">
                    <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-green-800">Success!</p>
                      <p className="text-sm text-green-700 whitespace-pre-line">{pdfSuccess}</p>
                      <p className="text-xs text-green-600 mt-2">
                        Excel file downloaded. Switch to the <button onClick={() => setActiveTab('compare')} className="underline font-semibold hover:text-green-800">BOM Comparison</button> tab to compare files.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              <div className="mt-6 pt-6 border-t border-blue-200">
                <p className="text-center text-sm text-gray-600 mb-2 font-semibold">
                  What this tool does:
                </p>
                <ul className="text-xs text-gray-600 max-w-xl mx-auto space-y-1">
                  <li className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-green-600 flex-shrink-0 mt-0.5" />
                    <span>Automatically detects BOM tables in engineering PDFs</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-green-600 flex-shrink-0 mt-0.5" />
                    <span>Handles merged cells, multi-line descriptions, and multi-page BOMs</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-green-600 flex-shrink-0 mt-0.5" />
                    <span>Generates clean Excel files ready for comparison (no manual cleanup needed)</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 text-green-600 flex-shrink-0 mt-0.5" />
                    <span>Maps to standard BOM format (MPN, Qty, Ref Des, Description)</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===== TAB 2: BOM Comparison ===== */}
      {activeTab === 'compare' && (
        <div>

      <div className="controls w-full flex items-center justify-between mb-6 gap-4 print:hidden">
        <div className="w-1/3" />
        <div className="flex-1 flex justify-center">
          <button onClick={clearFiles} className="btn-warning px-5">Start Fresh</button>
        </div>
        <div className="w-1/3 flex justify-end gap-3">
          <button onClick={handlePrint} className="btn-primary flex items-center gap-2 px-4">
            <Printer className="w-4 h-4" /> Print
          </button>
          <button onClick={exportToExcel} className="btn-primary flex items-center gap-2 px-4">
            <FileDown className="w-4 h-4" /> Export Excel
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8 print:hidden">
        {/* File 1 Upload */}
        <div className="card p-6">
          <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-primary-600" />
            File 1 (Original)
          </h3>
          <div
            {...getRootProps1()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all duration-200 ${
              isDragActive1
                ? 'border-primary-500 bg-primary-50'
                : 'border-gray-300 hover:border-primary-400 hover:bg-gray-50'
            }`}
          >
            <input {...getInputProps1()} />
            <Upload className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <p className="text-lg font-medium text-gray-700 mb-2">
              {isDragActive1 ? 'Drop the file here' : 'Drag & drop file here'}
            </p>
            <p className="text-gray-500">or click to browse</p>
            {file1 && (
              <div className="mt-4 p-3 bg-success-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className="w-5 h-5 text-success-600" />
                  <div>
                    <p className="font-medium text-success-800">{fileName1}</p>
                    <p className="text-sm text-success-600">
                      {(file1.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* File 2 Upload */}
        <div className="card p-6">
          <h3 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <FileSpreadsheet className="w-5 h-5 text-primary-600" />
            File 2 (New Version)
          </h3>
          <div
            {...getRootProps2()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all duration-200 ${
              isDragActive2
                ? 'border-primary-500 bg-primary-50'
                : 'border-gray-300 hover:border-primary-400 hover:bg-gray-50'
            }`}
          >
            <input {...getInputProps2()} />
            <Upload className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <p className="text-lg font-medium text-gray-700 mb-2">
              {isDragActive2 ? 'Drop the file here' : 'Drag & drop file here'}
            </p>
            <p className="text-gray-500">or click to browse</p>
            {file2 && (
              <div className="mt-4 p-3 bg-success-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className="w-5 h-5 text-success-600" />
                  <div>
                    <p className="font-medium text-success-800">{fileName2}</p>
                    <p className="text-sm text-success-600">
                      {(file2.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Step 1: Analyze Files Button */}
      {!showColumnSelection && (
        <div className="text-center mb-8">
          <button
            onClick={handleAnalyzeFiles}
            disabled={!file1 || !file2 || analyzing}
            className={`btn-primary flex items-center gap-2 mx-auto ${
              (!file1 || !file2 || analyzing) ? 'opacity-50 cursor-not-allowed' : ''
            }`}
          >
            {analyzing ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                Analyzing Files...
              </>
            ) : (
              <>
                <Search className="w-5 h-5" />
                Analyze Files & Select Columns
              </>
            )}
          </button>
          <p className="text-sm text-gray-600 mt-2">
            First, we&apos;ll analyze your files to detect available columns
          </p>
        </div>
      )}

      {/* Step 2: Column Selection Interface */}
      {showColumnSelection && analysisResults && (
        <div className="mb-8 p-6 bg-gray-50 rounded-lg">
          <h3 className="text-xl font-semibold mb-4 text-center">Step 2: Select Columns for Comparison</h3>
          <p className="text-center text-gray-600 mb-6">
            Choose which columns contain your part data. MPN (Part Number) is required.
          </p>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* File 1 Column Selection */}
            <div className="card p-4">
              <h4 className="font-semibold mb-3 flex items-center gap-2">
                <FileSpreadsheet className="w-4 h-4 text-blue-600" />
                File 1: {analysisResults.file1.filename}
              </h4>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    MPN / Part Number <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={selectedColumns.file1.mpn}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file1: { ...prev.file1, mpn: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file1.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Quantity</label>
                  <select
                    value={selectedColumns.file1.qty}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file1: { ...prev.file1, qty: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file1.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Reference Designator</label>
                  <select
                    value={selectedColumns.file1.refdes}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file1: { ...prev.file1, refdes: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file1.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <select
                    value={selectedColumns.file1.description}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file1: { ...prev.file1, description: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file1.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* File 2 Column Selection */}
            <div className="card p-4">
              <h4 className="font-semibold mb-3 flex items-center gap-2">
                <FileSpreadsheet className="w-4 h-4 text-green-600" />
                File 2: {analysisResults.file2.filename}
              </h4>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    MPN / Part Number <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={selectedColumns.file2.mpn}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file2: { ...prev.file2, mpn: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file2.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Quantity</label>
                  <select
                    value={selectedColumns.file2.qty}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file2: { ...prev.file2, qty: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file2.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Reference Designator</label>
                  <select
                    value={selectedColumns.file2.refdes}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file2: { ...prev.file2, refdes: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file2.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <select
                    value={selectedColumns.file2.description}
                    onChange={(e) => setSelectedColumns(prev => ({
                      ...prev,
                      file2: { ...prev.file2, description: e.target.value }
                    }))}
                    className="w-full p-2 border border-gray-300 rounded-md text-sm"
                  >
                    <option value="">Select column...</option>
                    {analysisResults.file2.columns.map(col => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* Step 3: Compare Button */}
          <div className="text-center mt-6">
            <button
              onClick={handleCompare}
              disabled={!selectedColumns.file1.mpn || !selectedColumns.file2.mpn || loading}
              className={`btn-primary flex items-center gap-2 mx-auto ${
                (!selectedColumns.file1.mpn || !selectedColumns.file2.mpn || loading) ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              {loading ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  Comparing...
                </>
              ) : (
                <>
                  <ArrowLeftRight className="w-5 h-5" />
                  Compare Files
                </>
              )}
            </button>
            <p className="text-sm text-gray-600 mt-2">
              MPN columns are required for both files
            </p>
          </div>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="bg-danger-50 border border-danger-200 rounded-lg p-4 mb-6">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-danger-600" />
            <span className="text-danger-800 font-medium">{error}</span>
          </div>
        </div>
      )}

      {/* Results */}
      {results && (
        <div className="space-y-6 print-area">

          {/* Stats removed per client request */}

          {/* Search Bar */}
          <div className="relative mb-6 search-bar print:hidden">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-5 w-5 text-gray-400" />
            </div>
            <input
              type="text"
              placeholder="Search parts by MPN or Ref Des..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md leading-5 bg-white placeholder-gray-500 focus:outline-none focus:placeholder-gray-400 focus:ring-1 focus:ring-primary-500 focus:border-primary-500 sm:text-sm"
            />
            {searchTerm && (
              <button
                onClick={() => setSearchTerm('')}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600"
              >
                <XCircle className="h-5 w-5" />
              </button>
            )}
          </div>

          {/* Summary cards for new 3-category model: Delete, Add, Change */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6 summary-cards">
            <CategoryCard
              title="Delete (in File 1 only)"
              count={filterResults(results, searchTerm).summary_stats.removed_parts_count}
              icon={XCircle}
              color="primary"
              onClick={() => toggleCategory('category-1')}
            />
            <CategoryCard
              title="Add (in File 2 only)"
              count={filterResults(results, searchTerm).summary_stats.new_parts_count}
              icon={CheckCircle}
              color="success"
              onClick={() => toggleCategory('category-2')}
            />
            <CategoryCard
              title="Change (Any differences)"
              count={filterResults(results, searchTerm).summary_stats.modified_parts_count}
              icon={AlertCircle}
              color="warning"
              onClick={() => toggleCategory('category-3')}
            />
          </div>

          {/* Detailed Results */}
          {renderPartComparisonView(filterResults(results, searchTerm))}
        </div>
      )}

        </div>
      )}
    </div>
  );
}

interface CategoryCardProps {
  title: string;
  count: number;
  icon: React.ComponentType<{ className?: string }>;
  color: 'success' | 'danger' | 'warning' | 'gray' | 'primary';
  onClick: () => void;
}

function CategoryCard({ title, count, icon: Icon, color, onClick }: CategoryCardProps) {
  const colorClasses = {
    success: 'bg-success-600 hover:bg-success-700',
    danger: 'bg-danger-600 hover:bg-danger-700',
    warning: 'bg-warning-600 hover:bg-warning-700',
    gray: 'bg-gray-600 hover:bg-gray-700',
    primary: 'bg-primary-600 hover:bg-primary-700',
  };

  return (
    <div
      className={`${colorClasses[color]} text-white p-4 rounded-lg cursor-pointer transition-colors duration-200`}
      onClick={onClick}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Icon className="w-5 h-5" />
          <span className="font-medium">{title}</span>
        </div>
        <span className="bg-white bg-opacity-20 px-3 py-1 rounded-full text-sm font-bold">
          {count}
        </span>
      </div>
    </div>
  );
}

interface CategoryDetailsProps {
  results: ComparisonResults;
  expandedCategories: Set<string>;
  toggleCategory: (categoryId: string) => void;
  fileName1: string;
  fileName2: string;
}

function CategoryDetails({ results, expandedCategories, toggleCategory, fileName1, fileName2 }: CategoryDetailsProps) {
  const renderPartTable = (parts: BOMPart[] | ModifiedPart[], isModified = false) => (
    <div className="overflow-x-auto">
      <table className="w-full bg-white border-2 border-gray-600 rounded-lg text-sm min-w-full border-collapse">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-2 py-2 text-left font-medium text-sm min-w-40 border border-gray-600">MPN</th>
            <th className="px-2 py-2 text-left font-medium text-sm min-w-24 border border-gray-600">Ref Des</th>
            <th className="px-2 py-2 text-left font-medium text-sm min-w-16 border border-gray-600">Qty</th>
              {/* Description and Line removed */}
          </tr>
        </thead>
        <tbody>
          {parts.map((part, index) => (
            <tr key={index}>
              <td className="px-2 py-2 font-medium text-primary-600 text-sm break-all min-w-40 border border-gray-600">{part.MPN}</td>
              <td className="px-2 py-2 text-sm break-all min-w-24 border border-gray-600">{isModified ? (part as ModifiedPart)['File1 Ref Des'] : (part as BOMPart)['Ref Des/LOC']}</td>
              <td className="px-2 py-2 text-sm min-w-16 border border-gray-600">{isModified ? (part as ModifiedPart)['File1 Qty'] : (part as BOMPart).Qty}</td>
                {/* Description and Line removed */}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderEmptyTable = (message: string) => (
    <div className="overflow-hidden">
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <div className="flex items-center gap-2 mb-3">
          <XCircle className="w-5 h-5 text-red-600" />
          <h4 className="font-semibold text-red-600 text-sm">{message}</h4>
        </div>
        <table className="w-full bg-white border border-gray-300 rounded-lg text-sm border-collapse">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-2 py-2 text-left font-medium text-sm min-w-40 border border-gray-200">MPN</th>
              <th className="px-2 py-2 text-left font-medium text-sm min-w-24 border border-gray-200">Ref Des</th>
              <th className="px-2 py-2 text-left font-medium text-sm min-w-16 border border-gray-200">Qty</th>
              <th className="px-2 py-2 text-left font-medium text-sm min-w-48 border border-gray-200">Description</th>
              <th className="px-2 py-2 text-left font-medium text-sm min-w-16 border border-gray-200">Line</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={5} className="px-2 py-8 text-center text-gray-400 text-sm border border-gray-200">
                No data available
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );

  const FileHeader = ({ fileName, color, position }: { fileName: string; color: string; position: 'left' | 'right' }) => (
    <div className={`flex items-center gap-2 mb-3 ${position === 'right' ? 'justify-end' : ''}`}>
      <div className={`px-3 py-1 rounded-t-lg ${color} text-white text-sm font-medium`}>
        {fileName || `File ${position === 'left' ? '1' : '2'}`}
      </div>
    </div>
  );
}

interface CategorySectionProps {
  id: string;
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  color: 'success' | 'danger' | 'warning' | 'gray' | 'primary';
  count: number;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function CategorySection({ id, title, icon: Icon, color, count, isExpanded, onToggle, children }: CategorySectionProps) {
  const colorClasses = {
    primary: 'bg-primary-600',
    success: 'bg-success-600', 
    danger: 'bg-danger-600',
    warning: 'bg-warning-600',
    gray: 'bg-gray-600'
  };

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div
        className={`${colorClasses[color]} text-white p-4 cursor-pointer flex items-center justify-between`}
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <Icon className="w-5 h-5" />
          <h3 className="font-semibold">{title}</h3>
          <span className="bg-white bg-opacity-20 px-3 py-1 rounded-full text-sm font-medium">
            {count} items
          </span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-5 h-5" />
        ) : (
          <ChevronDown className="w-5 h-5" />
        )}
      </div>
      <div className={`p-4 bg-gray-50 ${!isExpanded ? 'hidden' : ''} print:block`}>
        {children}
      </div>
    </div>
  );
}
