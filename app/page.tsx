'use client';

import React, { useState, useCallback, useEffect, useRef } from 'react';
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
  'File1 MPN'?: string;
  'File2 MPN'?: string;
  'File1 Ref Des': string;
  'File2 Ref Des': string;
  'File1 Qty': string;
  'File2 Qty': string;
  'File1 Description': string;
  'File2 Description': string;
  'File1 Line': string;
  'File2 Line': string;
  MPN_Changed?: boolean;
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

type ConvertPreviewPanelProps = {
  accentColor: 'blue' | 'purple';
  preview: {
    filename: string;
    columns: string[];
    rows: string[][];
    total_rows: number;
    preview_truncated: boolean;
    metadata?: {
      confidence?: number;
      rows_extracted?: number;
      extraction_method?: string;
      pages_processed?: number | number[];
      columns_detected?: string[];
    };
    warnings?: string[];
  };
  onDownload: () => void;
  onReset: () => void;
  onGoCompare: () => void;
};

function ConfidenceBadge({ value, columnConfidence, columns }: {
  value?: number;
  columnConfidence?: Record<string, number>;
  columns?: string[];
}) {
  const [open, setOpen] = useState(false);
  if (value === undefined || value === null) return null;
  const pct = Math.round(value * 100);
  let cls = 'bg-emerald-50 text-emerald-700 border-emerald-200';
  let label = 'High confidence';
  if (pct < 60) { cls = 'bg-rose-50 text-rose-700 border-rose-200'; label = 'Low confidence — review'; }
  else if (pct < 80) { cls = 'bg-amber-50 text-amber-700 border-amber-200'; label = 'Medium confidence'; }
  const hasDetails = (columnConfidence && Object.keys(columnConfidence).length > 0) || (columns && columns.length > 0);
  return (
    <div className="relative">
      <button
        onClick={() => hasDetails && setOpen(o => !o)}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-full border ${cls} ${hasDetails ? 'cursor-pointer hover:shadow-sm' : 'cursor-default'}`}
        title={hasDetails ? 'Click for per-column confidence' : `Extraction confidence: ${pct}%`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${pct >= 80 ? 'bg-emerald-500' : pct >= 60 ? 'bg-amber-500' : 'bg-rose-500'}`} />
        {pct}% · {label}
      </button>
      {open && hasDetails && (
        <div className="absolute z-30 top-full left-0 mt-2 w-72 card p-3 animate-fade-up">
          <p className="text-xs font-semibold text-app mb-2">Per-column confidence</p>
          <ul className="space-y-1.5">
            {columns?.map(col => {
              const score = columnConfidence?.[col];
              const sPct = score !== undefined ? Math.round(score * 100) : null;
              return (
                <li key={col} className="flex items-center gap-2 text-xs">
                  <span className="flex-1 truncate text-app-muted">{col}</span>
                  {sPct !== null ? (
                    <>
                      <div className="w-16 h-1.5 surface-inset rounded-full overflow-hidden">
                        <div
                          className="h-full"
                          style={{
                            width: `${sPct}%`,
                            background: sPct >= 80 ? '#10b981' : sPct >= 60 ? '#f59e0b' : '#f43f5e',
                          }}
                        />
                      </div>
                      <span className="font-mono tabular-nums text-app w-9 text-right">{sPct}%</span>
                    </>
                  ) : (
                    <span className="text-app-subtle text-[10px]">—</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function MethodBadge({ method }: { method?: string }) {
  if (!method) return null;
  const labels: Record<string, string> = {
    grid: 'Grid-detected',
    words: 'Word-bucketed',
    text: 'Text-only fallback',
  };
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-gray-600 bg-gray-100 border border-gray-200 rounded-full" title="How the table was detected">
      <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
      {labels[method] ?? method}
    </span>
  );
}

function ConvertPreviewPanel({ accentColor, preview, onDownload, onReset, onGoCompare }: ConvertPreviewPanelProps) {
  const [closed, setClosed] = useState(false);
  const [copied, setCopied] = useState(false);
  const accentText = accentColor === 'purple' ? 'text-purple-600' : 'text-blue-600';

  const handleCopy = async () => {
    // Copy TSV to clipboard — paste directly into any spreadsheet
    const tsv = [
      preview.columns.join('\t'),
      ...preview.rows.map(r => r.join('\t')),
    ].join('\n');
    try {
      await navigator.clipboard.writeText(tsv);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };

  return (
    <div className="mx-4 mb-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header bar: "Result (N)" + Start Over */}
      <div className="px-6 py-4 flex items-center justify-between">
        <p className="text-lg text-gray-700">
          Result <span className="font-bold text-gray-900">({preview.total_rows})</span>
        </p>
        <button
          onClick={() => { setClosed(false); onReset(); }}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 shadow-sm transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Start Over
        </button>
      </div>

      {/* File row */}
      <div className="px-6 py-3 border-t border-gray-100 flex flex-wrap items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-green-600 flex items-center justify-center shadow-sm">
          <span className="text-white text-[10px] font-bold tracking-wide">XLSX</span>
        </div>
        <p className="font-medium text-gray-900 flex-1 min-w-[120px] truncate">{preview.filename}</p>
        <ConfidenceBadge
          value={preview.metadata?.confidence}
          columnConfidence={(preview.metadata as any)?.column_confidence}
          columns={preview.metadata?.columns_detected}
        />
        <MethodBadge method={preview.metadata?.extraction_method} />
        <span className={`px-3 py-1 text-xs font-semibold ${accentText} bg-blue-50 rounded-full`}>
          Finished
        </span>
        <button
          onClick={() => setClosed(c => !c)}
          className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          {closed ? 'Show Preview' : 'Close Preview'}
        </button>
        <button
          onClick={handleCopy}
          className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
        <button
          onClick={onDownload}
          className="px-4 py-1.5 text-sm font-semibold text-white bg-gray-900 rounded-lg hover:bg-black transition-colors shadow-sm"
        >
          Download
        </button>
      </div>

      {preview.warnings && preview.warnings.length > 0 && (
        <div className="mx-6 mb-2 px-4 py-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
          <span className="font-semibold">Note:</span> {preview.warnings.join(' · ')}
        </div>
      )}

      {/* Table */}
      {!closed && (
        <div className="border-t border-gray-100 overflow-auto max-h-[480px]">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 shadow-[0_1px_0_0_rgba(0,0,0,0.06)]">
              <tr>
                {preview.columns.map((col, i) => (
                  <th
                    key={i}
                    className="px-4 py-3 text-center text-[13px] font-semibold text-gray-700 whitespace-nowrap bg-gray-50/95 backdrop-blur"
                  >
                    {col || `Column ${i + 1}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.length === 0 && (
                <tr>
                  <td colSpan={preview.columns.length} className="px-4 py-8 text-center text-sm text-gray-500">
                    No data rows extracted.
                  </td>
                </tr>
              )}
              {preview.rows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50/70'}>
                  {preview.columns.map((_, ci) => (
                    <td
                      key={ci}
                      className="px-4 py-3 text-[13px] text-gray-800 text-center align-middle whitespace-pre-wrap break-words"
                    >
                      {row[ci] ?? ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {preview.preview_truncated && !closed && (
        <div className="px-6 py-2 text-center text-xs text-gray-500 border-t border-gray-100">
          Showing first {preview.rows.length} of {preview.total_rows} rows. The full file is in the download.
        </div>
      )}

      <div className="px-6 py-3 border-t border-gray-100 text-xs text-gray-500 flex items-center justify-between">
        <span>
          Need to compare?{' '}
          <button onClick={onGoCompare} className="underline font-semibold text-gray-700 hover:text-gray-900">
            Open BOM Comparison
          </button>
        </span>
        <span className="flex items-center gap-1 text-gray-400">
          Rate your experience
          {[1, 2, 3, 4, 5].map(n => (
            <svg key={n} className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 17.27l5.18 3.13-1.37-5.9L20.5 9.74l-6.05-.52L12 3.5 9.55 9.22l-6.05.52 4.69 4.76-1.37 5.9z" opacity="0.3" />
            </svg>
          ))}
        </span>
      </div>
    </div>
  );
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

  // Tab state — synced to URL hash so refresh + share-link land on the same tool.
  const [activeTab, setActiveTab] = useState<'pdf' | 'image' | 'compare'>(() => {
    if (typeof window === 'undefined') return 'pdf';
    const h = (window.location.hash || '').replace('#', '');
    return (['pdf', 'image', 'compare'] as const).includes(h as any) ? (h as any) : 'pdf';
  });
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const want = `#${activeTab}`;
    if (window.location.hash !== want) window.history.replaceState(null, '', want);
  }, [activeTab]);
  useEffect(() => {
    const onHash = () => {
      const h = (window.location.hash || '').replace('#', '');
      if ((['pdf', 'image', 'compare'] as const).includes(h as any) && h !== activeTab) {
        setActiveTab(h as any);
      }
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [activeTab]);

  // Toast system — small utility for transient success/error feedback.
  type Toast = { id: number; kind: 'success' | 'error' | 'info'; msg: string };
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toast = useCallback((msg: string, kind: Toast['kind'] = 'info') => {
    const id = Date.now() + Math.random();
    setToasts(t => [...t, { id, kind, msg }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);

  // Settings / help drawer state
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [fuzzyThreshold, setFuzzyThreshold] = useState<number>(() => {
    if (typeof window === 'undefined') return 0.88;
    try {
      const v = parseFloat(localStorage.getItem('toolsuite.fuzzyThreshold') || '0.88');
      return isNaN(v) ? 0.88 : Math.max(0.5, Math.min(1, v));
    } catch { return 0.88; }
  });
  useEffect(() => {
    try { localStorage.setItem('toolsuite.fuzzyThreshold', String(fuzzyThreshold)); } catch {}
  }, [fuzzyThreshold]);

  // Manually-rejected fuzzy MPN pairs, persisted across sessions
  const [ignoredPairs, setIgnoredPairs] = useState<[string, string][]>(() => {
    if (typeof window === 'undefined') return [];
    try { return JSON.parse(localStorage.getItem('toolsuite.ignoredPairs') || '[]'); }
    catch { return []; }
  });
  useEffect(() => {
    try { localStorage.setItem('toolsuite.ignoredPairs', JSON.stringify(ignoredPairs)); } catch {}
  }, [ignoredPairs]);

  // Revision auto-detection from filename + workbook header (server-side parse)
  const [revInfo, setRevInfo] = useState<{ file1?: string | null; file2?: string | null }>({});

  // Server-backed MPN alias dictionary (cross-references). Lazy-loaded the
  // first time the Settings drawer opens to avoid an extra request on cold
  // pageload.
  type AliasPair = { mpn_a: string; mpn_b: string; note?: string; created_at?: string };
  const [aliasPairs, setAliasPairs] = useState<AliasPair[]>([]);
  const [aliasLoading, setAliasLoading] = useState(false);

  const loadAliasPairs = useCallback(async () => {
    setAliasLoading(true);
    try {
      const res = await axios.get(`${getApiBasePath()}/aliases`, {
        headers: { 'ngrok-skip-browser-warning': 'true' },
      });
      setAliasPairs(res.data?.pairs || []);
    } catch (e) {
      // Silent — backend might not be available in dev
    } finally {
      setAliasLoading(false);
    }
  }, []);

  const addAliasPair = useCallback(async (a: string, b: string, note?: string) => {
    try {
      await axios.post(`${getApiBasePath()}/aliases`, { mpn_a: a, mpn_b: b, note: note || '' });
      await loadAliasPairs();
      return true;
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Failed to add alias';
      console.error(msg);
      return false;
    }
  }, [loadAliasPairs]);

  const removeAliasPair = useCallback(async (a: string, b: string) => {
    try {
      await axios.delete(`${getApiBasePath()}/aliases`, { params: { mpn_a: a, mpn_b: b } });
      await loadAliasPairs();
    } catch (e) {
      console.error('Failed to remove alias', e);
    }
  }, [loadAliasPairs]);

  // Audit log
  type AuditEvent = {
    id: string;
    timestamp: string;
    kind: string;
    file1?: { name: string; sha256: string };
    file2?: { name: string; sha256: string };
    summary?: Record<string, any>;
    revision?: { file1?: string | null; file2?: string | null };
  };
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const loadAuditLog = useCallback(async () => {
    try {
      const res = await axios.get(`${getApiBasePath()}/audit-log`, {
        headers: { 'ngrok-skip-browser-warning': 'true' },
      });
      setAuditEvents(res.data?.events || []);
    } catch { /* ignore */ }
  }, []);

  // Column-mapping memory — recall the mapping the user picked last time we
  // saw a file matching this customer prefix. Keyed by the leading token
  // before '_' / '#' / ' ' (e.g. "IBML" from "IBML #7036 ..."). Avoids
  // making the user re-pick columns every time the same customer sends a
  // BOM in the same format.
  type SavedMapping = {
    mpn?: string; qty?: string; refdes?: string; description?: string;
    savedAt: string; sampleFile: string;
  };
  const MAPPING_STORE_KEY = 'toolsuite.columnMappings';
  const extractCustomerPrefix = useCallback((filename: string): string => {
    if (!filename) return '';
    const base = filename.replace(/\.(xlsx|xls|pdf|csv)$/i, '').trim();
    // Split on the first separator that typically follows the customer code
    const token = base.split(/[\s_#\-]+/)[0] || base;
    return token.toUpperCase().slice(0, 24);
  }, []);

  const loadMappingMemory = useCallback((filename: string): SavedMapping | null => {
    if (typeof window === 'undefined') return null;
    try {
      const all = JSON.parse(localStorage.getItem(MAPPING_STORE_KEY) || '{}');
      const key = extractCustomerPrefix(filename);
      return key && all[key] ? (all[key] as SavedMapping) : null;
    } catch { return null; }
  }, [extractCustomerPrefix]);

  const saveMappingMemory = useCallback((filename: string, mapping: SavedMapping) => {
    if (typeof window === 'undefined') return;
    try {
      const all = JSON.parse(localStorage.getItem(MAPPING_STORE_KEY) || '{}');
      const key = extractCustomerPrefix(filename);
      if (!key) return;
      all[key] = { ...mapping, savedAt: new Date().toISOString(), sampleFile: filename };
      localStorage.setItem(MAPPING_STORE_KEY, JSON.stringify(all));
    } catch { /* ignore */ }
  }, [extractCustomerPrefix]);

  // Template-export modal state
  type ExportDirection = 'file2-into-file1' | 'file1-into-file2';
  const [templateExportOpen, setTemplateExportOpen] = useState(false);
  const [templateExporting, setTemplateExporting] = useState(false);
  const [templateExportTint, setTemplateExportTint] = useState(true);
  const [templateExportDirection, setTemplateExportDirection] = useState<ExportDirection>('file2-into-file1');

  // Comparison-results sub-tab (Overview / Removed / Added / Modified / Renamed / Drift / Duplicates)
  type ResultsTab = 'overview' | 'removed' | 'added' | 'modified' | 'renamed' | 'drift' | 'duplicates';
  const [resultsTab, setResultsTab] = useState<ResultsTab>('overview');

  // Active filter chips for the modified-parts table
  const [modFilters, setModFilters] = useState<{ qty: boolean; refdes: boolean; description: boolean; manufacturer: boolean }>({
    qty: false, refdes: false, description: false, manufacturer: false,
  });

  // Shared preview result shape (returned by both converters)
  type ConvertPreview = {
    filename: string;
    columns: string[];
    rows: string[][];
    total_rows: number;
    preview_truncated: boolean;
    excel_base64: string;
    mime?: string;
    metadata?: { confidence?: number; rows_extracted?: number; pages_processed?: number | number[] };
    warnings?: string[];
  };

  // PDF to Excel conversion states
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfProcessing, setPdfProcessing] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [pdfPreview, setPdfPreview] = useState<ConvertPreview | null>(null);
  // Conversion mode: 'bom' = BOM-aware (normalize columns, AI fallback);
  // 'normal' = generic any-PDF table extraction. And the output file format.
  const [pdfMode, setPdfMode] = useState<'bom' | 'normal'>('bom');
  const [pdfFormat, setPdfFormat] = useState<'excel' | 'word'>('excel');
  const [pdfProgress, setPdfProgress] = useState(0);
  const [pdfStage, setPdfStage] = useState('');

  // Image (JPG/PNG) → Excel conversion states
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imageProcessing, setImageProcessing] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<ConvertPreview | null>(null);
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
      setPdfPreview(null);
    }
  }, []);

  const { getRootProps: getRootPropsPdf, getInputProps: getInputPropsPdf, isDragActive: isDragActivePdf } = useDropzone({
    onDrop: onDropPdf,
    accept: {
      'application/pdf': ['.pdf'],
    },
    multiple: false,
  });

  // Image (JPG/PNG) dropzone
  const onDropImage = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setImageFile(acceptedFiles[0]);
      setImageError(null);
      setImagePreview(null);
    }
  }, []);
  const { getRootProps: getRootPropsImage, getInputProps: getInputPropsImage, isDragActive: isDragActiveImage } = useDropzone({
    onDrop: onDropImage,
    accept: {
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
    },
    multiple: false,
  });

  // Keyboard shortcuts — `/` focuses search, `g` then `1/2/3` jumps tools,
  // `Esc` closes any open drawer/modal. `?` toggles the help drawer.
  useEffect(() => {
    let lastKey = '';
    let lastKeyAt = 0;
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inForm = !!target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
      if (e.key === 'Escape') {
        if (settingsOpen) setSettingsOpen(false);
        else if (helpOpen) setHelpOpen(false);
      }
      if (inForm) return;
      if (e.key === '/') {
        const search = document.querySelector<HTMLInputElement>('input[type="search"], input[placeholder*="Search"]');
        if (search) { e.preventDefault(); search.focus(); }
      } else if (e.key === '?') {
        setHelpOpen(o => !o);
      } else if (e.key === 'g') {
        lastKey = 'g'; lastKeyAt = Date.now();
      } else if (lastKey === 'g' && Date.now() - lastKeyAt < 1000) {
        if (e.key === '1') setActiveTab('pdf');
        else if (e.key === '2') setActiveTab('image');
        else if (e.key === '3') setActiveTab('compare');
        lastKey = '';
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [settingsOpen, helpOpen]);

  // Paste-from-clipboard for the image tab — common workflow is "screenshot
  // a BOM table, switch to browser, hit ⌘V". Listen on window so the user
  // doesn't need to focus a specific element.
  useEffect(() => {
    if (activeTab !== 'image') return;
    const handler = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === 'file' && item.type.startsWith('image/')) {
          const file = item.getAsFile();
          if (file) {
            const ext = item.type.includes('png') ? 'png' : 'jpg';
            const named = new File([file], `pasted-${Date.now()}.${ext}`, { type: file.type });
            setImageFile(named);
            setImageError(null);
            setImagePreview(null);
          }
          e.preventDefault();
          break;
        }
      }
    };
    window.addEventListener('paste', handler);
    return () => window.removeEventListener('paste', handler);
  }, [activeTab]);

  const downloadPreviewExcel = (preview: ConvertPreview) => {
    const binary = atob(preview.excel_base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], {
      type: preview.mime || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = preview.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  };

  const handlePdfUpload = async () => {
    if (!pdfFile) {
      setPdfError('Please select a PDF file first.');
      return;
    }
    setPdfProcessing(true);
    setPdfError(null);
    setPdfPreview(null);
    setPdfProgress(0);
    setPdfStage('Uploading…');
    try {
      const formData = new FormData();
      formData.append('file', pdfFile);
      formData.append('mode', pdfMode);
      formData.append('output_format', pdfFormat);
      const apiUrl = `${getApiBasePath()}/pdf-to-excel`;
      const headers = { 'ngrok-skip-browser-warning': 'true' };

      // Conversion runs as an async job (BOM vision can take minutes — longer
      // than the edge proxy will hold one request). Enqueue, then poll.
      const start = await axios.post<any>(apiUrl, formData, {
        headers: { 'Content-Type': 'multipart/form-data', ...headers },
      });

      const finish = (data: ConvertPreview) => {
        setPdfPreview(data);
        if (pdfFile) pushRecent({ kind: 'pdf', label: pdfFile.name });
      };

      if (start.data?.status === 'done') {
        finish(start.data as ConvertPreview);
        return;
      }
      const jobId = start.data?.job_id;
      if (!jobId) throw new Error('Server did not return a job id.');

      // Poll up to ~20 minutes (large drawings via AI vision are slow).
      const statusUrl = `${apiUrl}/status/${jobId}`;
      const deadline = Date.now() + 20 * 60 * 1000;
      setPdfStage('Starting…');
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 2000));
        const s = await axios.get<any>(statusUrl, { headers });
        const st = s.data?.status;
        if (st === 'done') { setPdfProgress(100); finish(s.data as ConvertPreview); return; }
        if (st === 'error') { throw new Error(s.data?.detail || 'Conversion failed.'); }
        if (typeof s.data?.progress === 'number') setPdfProgress(s.data.progress);
        if (s.data?.stage) setPdfStage(s.data.stage);
      }
      throw new Error('Conversion timed out. Try Normal mode or a smaller PDF.');
    } catch (err: any) {
      console.error('PDF processing error:', err);
      const detail = err?.response?.data?.detail;
      setPdfError(detail || err?.message || 'PDF processing failed. Please try again.');
    } finally {
      setPdfProcessing(false);
    }
  };

  const handleImageUpload = async () => {
    if (!imageFile) {
      setImageError('Please select a JPG or PNG file first.');
      return;
    }
    setImageProcessing(true);
    setImageError(null);
    setImagePreview(null);
    try {
      const formData = new FormData();
      formData.append('file', imageFile);
      const apiUrl = `${getApiBasePath()}/image-to-excel`;
      const response = await axios.post<ConvertPreview>(apiUrl, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          'ngrok-skip-browser-warning': 'true',
        },
      });
      setImagePreview(response.data);
      if (imageFile) pushRecent({ kind: 'image', label: imageFile.name });
    } catch (err: any) {
      console.error('Image processing error:', err);
      const detail = err?.response?.data?.detail;
      setImageError(detail || err?.message || 'Image processing failed. Please try again.');
    } finally {
      setImageProcessing(false);
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
      // Pass user-tuned fuzzy threshold + manually-rejected MPN pairs.
      // (Backend is permissive and ignores unknown fields.)
      formData.append('fuzzy_threshold', String(fuzzyThreshold));
      formData.append('ignore_pairs', JSON.stringify(ignoredPairs));

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
      pushRecent({ kind: 'compare', label: `${fileName1 || 'File 1'} ↔ ${fileName2 || 'File 2'}` });
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

  // Detect revisions from filenames + first 20 rows of each workbook.
  // Fires on file-pick change, debounced.
  useEffect(() => {
    if (!file1 && !file2) {
      setRevInfo({});
      return;
    }
    if (!file1 || !file2) return;
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const fd = new FormData();
        fd.append('file1', file1);
        fd.append('file2', file2);
        const res = await axios.post(`${getApiBasePath()}/detect-revision`, fd, {
          headers: { 'Content-Type': 'multipart/form-data', 'ngrok-skip-browser-warning': 'true' },
          signal: ctrl.signal as any,
        });
        setRevInfo({
          file1: res.data?.file1?.revision || null,
          file2: res.data?.file2?.revision || null,
        });
      } catch { /* ignore — detection is best-effort */ }
    }, 400);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [file1, file2]);

  // Auto-apply remembered mapping when the user analyzes files for the
  // first time (the analyzeFiles handler still runs server-side to verify
  // the columns exist). We just pre-populate `selectedColumns`.
  useEffect(() => {
    if (!analysisResults) return;
    const remembered1 = loadMappingMemory(analysisResults.file1.filename);
    const remembered2 = loadMappingMemory(analysisResults.file2.filename);
    if (!remembered1 && !remembered2) return;
    const cols1 = new Set(analysisResults.file1.columns);
    const cols2 = new Set(analysisResults.file2.columns);
    const pick = (m: SavedMapping | null, cols: Set<string>, fallback: { mpn?: string; qty?: string; refdes?: string; description?: string }) => ({
      mpn: m?.mpn && cols.has(m.mpn) ? m.mpn : (fallback.mpn || ''),
      qty: m?.qty && cols.has(m.qty) ? m.qty : (fallback.qty || ''),
      refdes: m?.refdes && cols.has(m.refdes) ? m.refdes : (fallback.refdes || ''),
      description: m?.description && cols.has(m.description) ? m.description : (fallback.description || ''),
    });
    setSelectedColumns(curr => ({
      file1: pick(remembered1, cols1, curr.file1),
      file2: pick(remembered2, cols2, curr.file2),
    }));
    if (remembered1 || remembered2) {
      toast('Restored remembered column mapping', 'info');
    }
  }, [analysisResults]); // eslint-disable-line react-hooks/exhaustive-deps

  // After a successful compare, persist the mapping for future sessions
  useEffect(() => {
    if (!results || !analysisResults) return;
    saveMappingMemory(analysisResults.file1.filename, {
      ...selectedColumns.file1,
      savedAt: '', sampleFile: '',
    });
    saveMappingMemory(analysisResults.file2.filename, {
      ...selectedColumns.file2,
      savedAt: '', sampleFile: '',
    });
  }, [results]); // eslint-disable-line react-hooks/exhaustive-deps

  // ----- Template-export (preserve original styling) -----
  const runTemplateExport = async (direction: ExportDirection) => {
    if (!file1 || !file2) {
      toast('Select both files first', 'error');
      return;
    }
    if (!selectedColumns.file1.mpn || !selectedColumns.file2.mpn) {
      toast('Run a comparison first so columns are selected', 'error');
      return;
    }
    setTemplateExporting(true);
    try {
      const templateFile = direction === 'file2-into-file1' ? file1 : file2;
      const dataFile = direction === 'file2-into-file1' ? file2 : file1;
      const templateCols = direction === 'file2-into-file1' ? selectedColumns.file1 : selectedColumns.file2;
      const dataCols = direction === 'file2-into-file1' ? selectedColumns.file2 : selectedColumns.file1;

      // Build diff_meta from current results so cells can be tinted
      const diffMeta: Record<string, any> = {};
      if (results && templateExportTint) {
        const dataMpnKey = (p: any) => String(p['File2 MPN'] || p.MPN || '').toUpperCase().trim();
        const ownerMpnKey = (p: any) => String(direction === 'file2-into-file1' ? (p['File2 MPN'] || p.MPN) : (p['File1 MPN'] || p.MPN)).toUpperCase().trim();
        results.modified_parts.forEach(p => {
          const k = ownerMpnKey(p);
          if (!k) return;
          diffMeta[k] = {
            qty: String(p['File1 Qty']) !== String(p['File2 Qty']),
            refdes: String(p['File1 Ref Des']) !== String(p['File2 Ref Des']),
            description: String(p['File1 Description']) !== String(p['File2 Description']),
            mpn_changed: !!p.MPN_Changed,
          };
        });
        results.new_parts.forEach(p => {
          const k = String(p.MPN || '').toUpperCase().trim();
          if (k && direction === 'file2-into-file1') diffMeta[k] = { added: true };
        });
        results.removed_parts.forEach(p => {
          const k = String(p.MPN || '').toUpperCase().trim();
          if (k && direction === 'file2-into-file1') {
            diffMeta[k] = {
              removed: true,
              source_row: {
                mpn: p.MPN,
                qty: p.Qty,
                refdes: p['Ref Des/LOC'],
                description: p.Description,
              },
            };
          }
        });
      }

      const fd = new FormData();
      fd.append('template_file', templateFile);
      fd.append('data_file', dataFile);
      fd.append('template_mpn', templateCols.mpn);
      if (templateCols.qty) fd.append('template_qty', templateCols.qty);
      if (templateCols.refdes) fd.append('template_refdes', templateCols.refdes);
      if (templateCols.description) fd.append('template_description', templateCols.description);
      fd.append('data_mpn', dataCols.mpn);
      if (dataCols.qty) fd.append('data_qty', dataCols.qty);
      if (dataCols.refdes) fd.append('data_refdes', dataCols.refdes);
      if (dataCols.description) fd.append('data_description', dataCols.description);
      fd.append('tint', String(templateExportTint));
      if (Object.keys(diffMeta).length) fd.append('diff_meta', JSON.stringify(diffMeta));

      const res = await axios.post(`${getApiBasePath()}/export-as-template`, fd, {
        responseType: 'blob',
        headers: { 'Content-Type': 'multipart/form-data', 'ngrok-skip-browser-warning': 'true' },
        timeout: 180000,
      });
      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const tmpl = direction === 'file2-into-file1' ? (fileName1 || 'File1') : (fileName2 || 'File2');
      const base = tmpl.replace(/\.(xlsx|xls)$/i, '');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${base}__rewritten.xlsx`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(`Exported ${direction === 'file2-into-file1' ? 'File 2 data into File 1 template' : 'File 1 data into File 2 template'}`, 'success');
      setTemplateExportOpen(false);
    } catch (e: any) {
      const detail = e?.response?.data?.detail || e?.message || 'Template export failed';
      console.error('Template export failed', e);
      toast(detail, 'error');
    } finally {
      setTemplateExporting(false);
    }
  };

  // ----- PDF change-report -----
  const downloadPdfReport = async () => {
    if (!results) {
      toast('Run a comparison first', 'error');
      return;
    }
    try {
      const jspdf: any = await import('jspdf');
      const Doc = jspdf.jsPDF || (jspdf.default && (jspdf.default.jsPDF || jspdf.default)) || jspdf;
      const doc = new Doc({ unit: 'pt', format: 'letter' });
      const margin = 48;
      let y = margin;

      doc.setFont('helvetica', 'bold');
      doc.setFontSize(16);
      doc.text('BOM Comparison Report', margin, y);
      y += 22;
      doc.setFont('helvetica', 'normal');
      doc.setFontSize(10);
      doc.setTextColor(110);
      doc.text(new Date().toLocaleString(), margin, y);
      y += 18;
      doc.setTextColor(0);

      const fileLine = (label: string, name: string, rev?: string | null) => {
        doc.setFont('helvetica', 'bold');
        doc.text(`${label}:`, margin, y);
        doc.setFont('helvetica', 'normal');
        doc.text(` ${name || '(unnamed)'}${rev ? `   [Rev ${rev}]` : ''}`, margin + 50, y);
        y += 14;
      };
      fileLine('File 1', fileName1, revInfo.file1);
      fileLine('File 2', fileName2, revInfo.file2);
      y += 6;

      doc.setDrawColor(220); doc.line(margin, y, 612 - margin, y); y += 18;

      const s = results.summary_stats;
      const total = (s.total_parts_file1 || 0) + (s.total_parts_file2 || 0);
      const matchPct = total > 0 ? Math.round((s.unchanged_parts_count * 2 / total) * 100) : 0;

      doc.setFontSize(34);
      doc.setFont('helvetica', 'bold');
      doc.setTextColor(16, 132, 120);
      doc.text(`${matchPct}%`, margin, y + 28);
      doc.setTextColor(0);
      doc.setFontSize(11);
      doc.setFont('helvetica', 'normal');
      doc.text('match rate', margin + 70, y + 24);
      y += 50;

      const stat = (label: string, count: number, color: [number, number, number]) => {
        doc.setFont('helvetica', 'bold'); doc.setFontSize(14);
        doc.setTextColor(...color); doc.text(String(count), margin, y);
        doc.setTextColor(0); doc.setFontSize(10);
        doc.setFont('helvetica', 'normal');
        doc.text(label, margin + 48, y);
        y += 16;
      };
      stat('Removed (in File 1 only)', s.removed_parts_count, [220, 38, 38]);
      stat('Added (in File 2 only)', s.new_parts_count, [22, 163, 74]);
      stat('Modified (any difference)', s.modified_parts_count, [217, 119, 6]);
      stat('Unchanged', s.unchanged_parts_count, [75, 85, 99]);
      const renamed = results.modified_parts.filter(p => p.MPN_Changed).length;
      if (renamed) stat('MPN renamed', renamed, [126, 34, 206]);

      y += 8;
      doc.setDrawColor(220); doc.line(margin, y, 612 - margin, y); y += 18;

      const sectionList = (title: string, items: any[], pick: (p: any) => string, max = 12) => {
        if (!items.length) return;
        doc.setFont('helvetica', 'bold'); doc.setFontSize(11);
        doc.text(title, margin, y); y += 14;
        doc.setFont('helvetica', 'normal'); doc.setFontSize(9);
        const slice = items.slice(0, max);
        slice.forEach(p => {
          if (y > 720) {
            doc.addPage(); y = margin;
          }
          doc.text(`• ${pick(p)}`, margin + 8, y);
          y += 12;
        });
        if (items.length > max) {
          doc.setTextColor(140);
          doc.text(`… and ${items.length - max} more`, margin + 8, y);
          doc.setTextColor(0);
          y += 14;
        } else {
          y += 4;
        }
      };

      sectionList('Removed parts', results.removed_parts, p => `${p.MPN}  —  qty ${p.Qty}, ref ${p['Ref Des/LOC']}`);
      sectionList('Added parts', results.new_parts, p => `${p.MPN}  —  qty ${p.Qty}, ref ${p['Ref Des/LOC']}`);
      sectionList('Modified parts', results.modified_parts, p =>
        `${p.MPN}: qty ${p['File1 Qty']}→${p['File2 Qty']}, ref ${p['File1 Ref Des']}→${p['File2 Ref Des']}`,
      );

      const safe1 = (fileName1 || 'File1').replace(/[^\w\-\.]+/g, '_');
      const safe2 = (fileName2 || 'File2').replace(/[^\w\-\.]+/g, '_');
      doc.save(`bom_report_${safe1}_vs_${safe2}.pdf`);
      toast('PDF report downloaded', 'success');
    } catch (e: any) {
      console.error('PDF report failed', e);
      toast('PDF report failed — is jspdf installed?', 'error');
    }
  };

  // ----- Rename-pair CSV export/import -----
  const exportRenamedCsv = () => {
    if (!results) {
      toast('Run a comparison first', 'error');
      return;
    }
    const renamed = results.modified_parts.filter(p => p.MPN_Changed);
    const rows = [
      ['mpn_a', 'mpn_b', 'note'],
      ...renamed.map(p => [p['File1 MPN'] || '', p['File2 MPN'] || '', 'auto-detected pair']),
    ];
    const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `renamed_pairs_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`Exported ${renamed.length} renamed pair${renamed.length === 1 ? '' : 's'}`, 'success');
  };

  const importRenamedCsv = async (file: File) => {
    try {
      const text = await file.text();
      const lines = text.split(/\r?\n/).filter(l => l.trim());
      if (!lines.length) return;
      // Skip header if first row contains 'mpn'
      const header = lines[0].toLowerCase();
      const dataLines = header.includes('mpn') ? lines.slice(1) : lines;
      const parsed = dataLines.map(line => {
        // simple CSV parse — handles quoted commas
        const out: string[] = []; let cur = ''; let inQ = false;
        for (let i = 0; i < line.length; i++) {
          const ch = line[i];
          if (inQ) {
            if (ch === '"') {
              if (line[i + 1] === '"') { cur += '"'; i++; }
              else inQ = false;
            } else cur += ch;
          } else {
            if (ch === ',') { out.push(cur); cur = ''; }
            else if (ch === '"') inQ = true;
            else cur += ch;
          }
        }
        out.push(cur);
        return out;
      });
      const pairs = parsed
        .map(cols => ({ mpn_a: (cols[0] || '').trim(), mpn_b: (cols[1] || '').trim(), note: (cols[2] || '').trim() }))
        .filter(p => p.mpn_a && p.mpn_b);
      if (!pairs.length) {
        toast('No valid pairs found in CSV', 'error');
        return;
      }
      const res = await axios.post(`${getApiBasePath()}/aliases/import`, { pairs });
      await loadAliasPairs();
      toast(`Imported ${res.data?.added || 0} alias(es), skipped ${res.data?.skipped || 0}`, 'success');
    } catch (e) {
      console.error('CSV import failed', e);
      toast('CSV import failed', 'error');
    }
  };

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

          // Data rows mirroring UI — sheet-specific row color coding makes
          // the diff scannable at a glance when opened in Excel.
          const rowFill =
            name.startsWith('Delete') ? 'FFFEE2E2' :   // rose-100
            name.startsWith('Add')    ? 'FFDCFCE7' :   // green-100
            name.startsWith('Renamed')? 'FFEDE9FE' :   // violet-100
                                          'FFFEF3C7';  // amber-100 (Change/Modified)
          rows.forEach((a: any[]) => {
            const row: any = sheet.addRow(a);
            row.eachCell((c: any) => {
              c.border = { top: { style: 'thin' }, left: { style: 'thin' }, bottom: { style: 'thin' }, right: { style: 'thin' } };
              c.alignment = { wrapText: true };
              c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: rowFill } };
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

        // Renamed-MPN sheet — surfaces the AI-paired parts with both old and new MPN.
        const renamedParts = results.modified_parts.filter(p => (p as any).MPN_Changed);
        if (renamedParts.length) {
          const renamedRows = renamedParts.map((p: any) => [
            `${p['File1 MPN'] || p.MPN} → ${p['File2 MPN'] || ''}`,
            p['File1 Ref Des'], p['File1 Qty'],
            p['File2 Ref Des'], p['File2 Qty'],
          ]);
          addStyledSheet('Renamed MPNs', `File 1: ${fileName1 || 'File 1'}`, `File 2: ${fileName2 || 'File 2'}`, renamedRows);
        }

        // ─── Side-by-side merged sheet ────────────────────────────────────
        // One row per MPN across both files plus a status column. Easier for
        // buyers to review than flipping between Change/Delete/Add tabs.
        {
          const sbsSheet = workbook.addWorksheet('Side-by-side');
          sbsSheet.views = [{ state: 'frozen', ySplit: 2 }];
          sbsSheet.columns = [
            { width: 32 },  // MPN
            { width: 12 },  // Status
            { width: 24 },  // F1 RefDes
            { width: 10 },  // F1 Qty
            { width: 36 },  // F1 Desc
            { width: 24 },  // F2 RefDes
            { width: 10 },  // F2 Qty
            { width: 36 },  // F2 Desc
          ];
          const headRow1 = sbsSheet.addRow([
            'MPN', 'Status',
            `${fileName1 || 'File 1'}`, null, null,
            `${fileName2 || 'File 2'}`, null, null,
          ]);
          headRow1.font = { bold: true };
          headRow1.getCell(3).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'DBEAFE' } };
          headRow1.getCell(6).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'DCFCE7' } };
          sbsSheet.mergeCells(1, 3, 1, 5);
          sbsSheet.mergeCells(1, 6, 1, 8);
          const headRow2 = sbsSheet.addRow([
            'MPN', 'Status',
            'Ref Des', 'Qty', 'Description',
            'Ref Des', 'Qty', 'Description',
          ]);
          headRow2.font = { bold: true };
          [headRow1, headRow2].forEach((r: any) => r.eachCell((c: any) => {
            c.border = { top: { style: 'thin' }, left: { style: 'thin' }, bottom: { style: 'thin' }, right: { style: 'thin' } };
          }));

          type SbsRow = {
            mpn: string; status: string; color: string;
            f1Ref: string; f1Qty: string; f1Desc: string;
            f2Ref: string; f2Qty: string; f2Desc: string;
          };
          const rows: SbsRow[] = [];
          results.removed_parts.forEach(p => rows.push({
            mpn: p.MPN, status: 'Removed', color: 'FFFEE2E2',
            f1Ref: p['Ref Des/LOC'] || '', f1Qty: String(p.Qty || ''), f1Desc: p.Description || '',
            f2Ref: '', f2Qty: '', f2Desc: '',
          }));
          results.new_parts.forEach(p => rows.push({
            mpn: p.MPN, status: 'Added', color: 'FFDCFCE7',
            f1Ref: '', f1Qty: '', f1Desc: '',
            f2Ref: p['Ref Des/LOC'] || '', f2Qty: String(p.Qty || ''), f2Desc: p.Description || '',
          }));
          results.modified_parts.forEach(p => rows.push({
            mpn: p.MPN_Changed ? `${p['File1 MPN'] || p.MPN} → ${p['File2 MPN'] || ''}` : p.MPN,
            status: p.MPN_Changed ? 'Renamed' : 'Modified',
            color: p.MPN_Changed ? 'FFEDE9FE' : 'FFFEF3C7',
            f1Ref: p['File1 Ref Des'] || '', f1Qty: String(p['File1 Qty'] || ''), f1Desc: p['File1 Description'] || '',
            f2Ref: p['File2 Ref Des'] || '', f2Qty: String(p['File2 Qty'] || ''), f2Desc: p['File2 Description'] || '',
          }));
          rows.sort((a, b) => a.mpn.localeCompare(b.mpn));

          rows.forEach(r => {
            const row: any = sbsSheet.addRow([
              r.mpn, r.status,
              r.f1Ref, r.f1Qty, r.f1Desc,
              r.f2Ref, r.f2Qty, r.f2Desc,
            ]);
            row.eachCell((c: any) => {
              c.border = { top: { style: 'thin' }, left: { style: 'thin' }, bottom: { style: 'thin' }, right: { style: 'thin' } };
              c.alignment = { wrapText: true, vertical: 'top' };
              c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: r.color } };
            });
            // Make the status column bold
            row.getCell(2).font = { bold: true };
          });
        }

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
    
    // Search now matches MPN, RefDes, Description AND line numbers across
    // both old and new sides for modified parts.
    const matchAny = (...vals: any[]) => vals.some(v => v !== undefined && v !== null && String(v).toLowerCase().includes(searchLower));

    const filterParts = (parts: BOMPart[]) =>
      parts.filter(part => matchAny(
        part.MPN, part['Ref Des/LOC'], part.Description, part.Qty, part['Line Number'],
      ));

    const filterModifiedParts = (parts: ModifiedPart[]) =>
      parts.filter(part => matchAny(
        part.MPN, part['File1 MPN'], part['File2 MPN'],
        part['File1 Ref Des'], part['File2 Ref Des'],
        part['File1 Description'], part['File2 Description'],
        part['File1 Qty'], part['File2 Qty'],
        part['File1 Line'], part['File2 Line'],
      ));

    // Apply Modified filter chips on top of search
    const applyModFilters = (parts: ModifiedPart[]) =>
      parts.filter(p => {
        const f = (p as any).flags;
        if (!f) return true;
        const active = (modFilters.qty ? !!f.qty : true)
          && (modFilters.refdes ? !!f.refdes : true)
          && (modFilters.description ? !!f.description : true)
          && (modFilters.manufacturer ? !!f.manufacturer : true);
        return active;
      });
    
    return {
      ...results,
      new_parts: filterParts(results.new_parts),
      removed_parts: filterParts(results.removed_parts),
      modified_parts: applyModFilters(filterModifiedParts(results.modified_parts)),
      unchanged_parts: filterParts(results.unchanged_parts),
      unrecognized_parts: filterParts(results.unrecognized_parts),
      summary_stats: {
        ...results.summary_stats,
        new_parts_count: filterParts(results.new_parts).length,
        removed_parts_count: filterParts(results.removed_parts).length,
        modified_parts_count: applyModFilters(filterModifiedParts(results.modified_parts)).length,
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

  const renderPartComparisonView = (results: ComparisonResults) => {
    const renamed = results.modified_parts.filter(p => p.MPN_Changed).length;
    const totalCompared = results.summary_stats.total_parts_file1 + results.summary_stats.total_parts_file2;
    const matchPct = totalCompared > 0
      ? Math.round((results.summary_stats.unchanged_parts_count * 2 / totalCompared) * 100)
      : 0;

    const dupCount = (results as any).summary_stats?.duplicate_mpn_count || 0;
    const driftCount = (results as any).summary_stats?.description_drift_count || 0;

    const tabBtn = (id: ResultsTab, label: string, count: number, color: string) => (
      <button
        onClick={() => setResultsTab(id)}
        className={`flex-1 sm:flex-initial px-4 py-3 rounded-lg text-left transition-all border ${
          resultsTab === id
            ? 'border-app surface shadow-card'
            : 'border-transparent hover:surface-subtle text-app-muted'
        }`}
      >
        <div className={`text-2xl font-bold ${color}`}>{count}</div>
        <div className="text-xs uppercase tracking-wider text-app-subtle mt-0.5">{label}</div>
      </button>
    );

    return (
    <div className="space-y-6 category-section">
      {/* Match-rate hero + tabbed sub-nav (replaces the wall of category sections) */}
      <div className="print:hidden">
        <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
          <div>
            <div className="text-3xl sm:text-4xl font-bold text-app">
              <span className="bg-gradient-to-br from-emerald-500 to-teal-500 bg-clip-text text-transparent">{matchPct}%</span>
              <span className="text-base font-normal text-app-muted ml-2">match rate</span>
            </div>
            <p className="text-sm text-app-subtle mt-1">
              {results.summary_stats.unchanged_parts_count} unchanged ·
              {' '}{results.summary_stats.modified_parts_count} modified ·
              {' '}{results.summary_stats.removed_parts_count + results.summary_stats.new_parts_count} added/removed
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-app-subtle">
            <span>Threshold</span>
            <span className="px-2 py-0.5 surface-inset rounded font-mono tabular-nums">{Math.round(((results as any).summary_stats?.fuzzy_threshold ?? 0.88) * 100)}%</span>
          </div>
        </div>

        {/* Click-through tab cards (act as both filter chips and tabs) */}
        <div className="flex flex-wrap gap-2 mb-4 border border-app rounded-2xl p-1.5 surface">
          {tabBtn('overview',   'Overview',  results.summary_stats.unchanged_parts_count, 'text-emerald-600')}
          {tabBtn('removed',    'Removed',   results.summary_stats.removed_parts_count,    'text-rose-600')}
          {tabBtn('added',      'Added',     results.summary_stats.new_parts_count,        'text-blue-600')}
          {tabBtn('modified',   'Modified',  results.summary_stats.modified_parts_count,   'text-amber-600')}
          {tabBtn('renamed',    'Renamed',   renamed,                                       'text-purple-600')}
          {driftCount > 0 && tabBtn('drift', 'Description drift', driftCount, 'text-fuchsia-600')}
          {dupCount > 0 && tabBtn('duplicates', 'Duplicates', dupCount, 'text-amber-700')}
        </div>

        {/* Filter chips active only on the Modified tab */}
        {resultsTab === 'modified' && (
          <div className="flex flex-wrap gap-2 mb-4 text-xs">
            {(['qty', 'refdes', 'description', 'manufacturer'] as const).map(k => (
              <button
                key={k}
                onClick={() => setModFilters(f => ({ ...f, [k]: !f[k] }))}
                className={`px-3 py-1.5 rounded-full border transition-colors ${
                  modFilters[k]
                    ? 'bg-[var(--accent-soft)] border-[var(--accent-border)] text-[var(--accent)]'
                    : 'border-app text-app-muted hover:surface-subtle'
                }`}
              >
                {modFilters[k] ? '✓ ' : ''}{k === 'qty' ? 'Qty changed' : k === 'refdes' ? 'Ref Des changed' : k === 'description' ? 'Description changed' : 'Manufacturer changed'}
              </button>
            ))}
            {(modFilters.qty || modFilters.refdes || modFilters.description || modFilters.manufacturer) && (
              <button
                onClick={() => setModFilters({ qty: false, refdes: false, description: false, manufacturer: false })}
                className="px-3 py-1.5 rounded-full border border-app text-app-subtle hover:surface-subtle"
              >
                Clear filters
              </button>
            )}
          </div>
        )}
      </div>

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

      {/* Category 1: Delete (screen only) — visible when resultsTab is overview/removed */}
      <div className={`print:hidden ${resultsTab === 'overview' || resultsTab === 'removed' ? '' : 'hidden'}`}>
        <CategorySection
            id="category-1"
            title="Removed (parts only in File 1)"
            icon={XCircle}
            color="primary"
            count={results.summary_stats.removed_parts_count}
            isExpanded={expandedCategories.has('category-1') || resultsTab === 'removed'}
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
      <div className={`${resultsTab === 'overview' || resultsTab === 'added' ? '' : 'hidden'} print:block`}>
      <CategorySection
        id="category-2"
        title="Added (parts only in File 2)"
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
      </div>

      {/* Category 3: Change (Parts with ANY Differences) */}
      <div className={`${resultsTab === 'overview' || resultsTab === 'modified' || resultsTab === 'renamed' ? '' : 'hidden'} print:block`}>
      <CategorySection
        id="category-3"
        title="Modified (parts with any differences)"
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
                      <td className="px-2 py-2 font-medium text-primary-600 text-sm break-all min-w-40 sticky left-0 z-10 bg-white border border-gray-700">
                        {part.MPN_Changed && part['File1 MPN'] && part['File2 MPN'] ? (
                          <div className="flex flex-col gap-1">
                            <span className="inline-flex items-center gap-1 self-start px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-purple-700 bg-purple-100 border border-purple-200 rounded-full">
                              <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" strokeWidth="3" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M16 3l4 4m0 0l-4 4m4-4H4m0 6h12m0 0l-4-4m4 4l-4 4" /></svg>
                              MPN renamed
                            </span>
                            <span className="text-rose-700 font-mono text-xs line-through">{part['File1 MPN']}</span>
                            <span className="text-emerald-700 font-mono text-xs">→ {part['File2 MPN']}</span>
                          </div>
                        ) : (
                          part.MPN
                        )}
                      </td>

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

      {/* Renamed-MPN dedicated panel (visible when 'renamed' tab is active) */}
      <div className={`${resultsTab === 'renamed' ? '' : 'hidden'} print:hidden`}>
        <RenamedPartsPanel
          parts={results.modified_parts.filter(p => p.MPN_Changed)}
          fileName1={fileName1}
          fileName2={fileName2}
          onReject={(a, b) => {
            setIgnoredPairs(prev => [...prev, [a, b]]);
            toast(`Rejected pair ${a} ↔ ${b}. Re-run comparison to apply.`, 'success');
          }}
        />
      </div>

      {/* Description drift panel */}
      <div className={`${resultsTab === 'drift' ? '' : 'hidden'} print:hidden`}>
        <DescriptionDriftPanel parts={(results as any).description_drift_parts || []} />
      </div>

      {/* Duplicate MPN warnings */}
      <div className={`${resultsTab === 'duplicates' ? '' : 'hidden'} print:hidden`}>
        <DuplicateMpnPanel warnings={(results as any).duplicate_mpn_warnings || []} />
      </div>
    </div>
    );
  };

  return (
    <AppShell
      activeTab={activeTab}
      setActiveTab={setActiveTab}
      onOpenSettings={() => setSettingsOpen(true)}
      onOpenHelp={() => setHelpOpen(true)}
    >
      {/* Section header — replaces the giant gradient hero with a tight,
          context-aware title that reflects which tool is active. */}
      <SectionHeader activeTab={activeTab} />

      {/* Step-progress overlay for active conversions */}
      {(pdfProcessing || imageProcessing || loading) && (
        <ProcessingOverlay phase={pdfProcessing ? 'pdf' : imageProcessing ? 'image' : 'compare'} />
      )}

      {/* Toast rack */}
      <ToastRack toasts={toasts} onDismiss={(id: number) => setToasts(t => t.filter(x => x.id !== id))} />

      {/* Settings drawer */}
      {settingsOpen && (
        <SettingsDrawer
          onClose={() => setSettingsOpen(false)}
          fuzzyThreshold={fuzzyThreshold}
          setFuzzyThreshold={setFuzzyThreshold}
          ignoredPairs={ignoredPairs}
          onClearIgnored={() => { setIgnoredPairs([]); toast('Cleared rejected MPN pairs', 'success'); }}
          aliasPairs={aliasPairs}
          aliasLoading={aliasLoading}
          onLoadAliases={loadAliasPairs}
          onAddAlias={addAliasPair}
          onRemoveAlias={removeAliasPair}
          onImportRenamedCsv={importRenamedCsv}
          auditEvents={auditEvents}
          onLoadAudit={loadAuditLog}
          onClearAudit={async () => {
            try {
              await axios.delete(`${getApiBasePath()}/audit-log`);
              setAuditEvents([]);
              toast('Audit log cleared', 'success');
            } catch { toast('Clear failed', 'error'); }
          }}
        />
      )}

      {/* Help drawer */}
      {helpOpen && <HelpDrawer onClose={() => setHelpOpen(false)} />}

      {/* Template-export modal */}
      {templateExportOpen && (
        <TemplateExportModal
          fileName1={fileName1}
          fileName2={fileName2}
          revInfo={revInfo}
          direction={templateExportDirection}
          setDirection={setTemplateExportDirection}
          tint={templateExportTint}
          setTint={setTemplateExportTint}
          loading={templateExporting}
          onClose={() => setTemplateExportOpen(false)}
          onExport={() => runTemplateExport(templateExportDirection)}
        />
      )}

      {/* ===== TAB 1: PDF to Excel Converter ===== */}
      {activeTab === 'pdf' && (
        <div className="print:hidden">
          <div className="max-w-3xl mx-auto">

            {/* Conversion mode + output format selectors */}
            <div className="mb-5 flex flex-col sm:flex-row gap-4 sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Conversion</p>
                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-0.5">
                  {([
                    ['bom', 'BOM Conversion', 'Detect & normalize the BOM (AI-assisted)'],
                    ['normal', 'Normal PDF → Excel', 'Extract any PDF table as-is'],
                  ] as const).map(([id, label, hint]) => (
                    <button
                      key={id}
                      type="button"
                      title={hint}
                      onClick={() => { setPdfMode(id); setPdfPreview(null); }}
                      className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                        pdfMode === id ? 'bg-blue-600 text-white shadow-sm' : 'text-gray-600 hover:bg-gray-100'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Output format</p>
                <div className="inline-flex rounded-lg border border-gray-300 bg-white p-0.5">
                  {([['excel', 'Excel'], ['word', 'Word']] as const).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => { setPdfFormat(id); setPdfPreview(null); }}
                      className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                        pdfFormat === id ? 'bg-emerald-600 text-white shadow-sm' : 'text-gray-600 hover:bg-gray-100'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Drop zone card */}
            <div className="card overflow-hidden">
              <div
                {...getRootPropsPdf()}
                className={`relative border-2 border-dashed m-4 rounded-xl p-10 text-center cursor-pointer transition-all duration-200 ${
                  isDragActivePdf
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-300 hover:border-blue-400 hover:bg-blue-50/40 surface-subtle'
                }`}
              >
                <input {...getInputPropsPdf()} />
                <div className="flex items-center justify-center gap-3 mb-5">
                  <div className="w-14 h-14 rounded-xl bg-red-100 flex items-center justify-center">
                    <svg className="w-8 h-8 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                  </svg>
                  <div className="w-14 h-14 rounded-xl bg-green-100 flex items-center justify-center">
                    <FileSpreadsheet className="w-8 h-8 text-green-600" />
                  </div>
                </div>
                <p className="text-xl font-semibold text-gray-800 mb-1">
                  {isDragActivePdf ? 'Drop your PDF here' : 'Drop PDF here'}
                </p>
                <p className="text-gray-500 mb-4">or click to browse from your computer</p>
                <div className="inline-flex items-center gap-2 text-xs text-gray-400">
                  <span className="px-2 py-1 bg-gray-100 rounded">.pdf</span>
                  <span>· digitally generated · 16 MB max</span>
                </div>
                {pdfFile && (
                  <div className="mt-5 inline-flex items-center gap-3 px-4 py-3 bg-white border border-blue-200 rounded-lg shadow-sm">
                    <div className="w-10 h-10 rounded-lg bg-red-100 flex items-center justify-center">
                      <svg className="w-5 h-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <div className="text-left">
                      <p className="font-medium text-gray-900 truncate max-w-xs">{pdfFile.name}</p>
                      <p className="text-xs text-gray-500">{(pdfFile.size / 1024).toFixed(1)} KB</p>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); setPdfFile(null); }}
                      className="ml-2 text-gray-400 hover:text-red-500 transition-colors"
                      aria-label="Remove file"
                    >
                      <XCircle className="w-5 h-5" />
                    </button>
                  </div>
                )}
              </div>

              <div className="px-6 pb-6 pt-2 flex items-center justify-center gap-3 flex-wrap">
                <button
                  onClick={handlePdfUpload}
                  disabled={!pdfFile || pdfProcessing}
                  className="btn-primary px-8 py-3 rounded-xl"
                >
                  {pdfProcessing ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current"></div>
                      {pdfMode === 'bom' ? 'Extracting BOM…' : 'Converting…'}
                    </>
                  ) : (
                    <>
                      <FileDown className="w-5 h-5" />
                      Convert to {pdfFormat === 'word' ? 'Word' : 'Excel'}
                    </>
                  )}
                </button>
                <button
                  onClick={async () => {
                    try {
                      const r = await fetch(`${getApiBasePath()}/sample-files`);
                      const data = await r.json();
                      const sample = data.samples?.find((s: any) => s.kind === 'pdf');
                      if (!sample) { toast('No sample PDF available', 'error'); return; }
                      const fr = await fetch(`${getApiBasePath()}/sample-files/${encodeURIComponent(sample.name)}`);
                      const blob = await fr.blob();
                      const f = new File([blob], sample.name, { type: 'application/pdf' });
                      setPdfFile(f);
                      toast(`Loaded sample ${sample.name}`, 'success');
                    } catch {
                      toast('Could not load sample file', 'error');
                    }
                  }}
                  className="btn-secondary"
                  type="button"
                >
                  Try a sample
                </button>
              </div>

              {pdfProcessing && (
                <div className="mx-4 mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-blue-800">{pdfStage || 'Working…'}</span>
                    <span className="text-sm font-mono tabular-nums text-blue-700">{pdfProgress}%</span>
                  </div>
                  <div className="w-full h-2.5 bg-blue-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-600 rounded-full transition-all duration-500 ease-out"
                      style={{ width: `${Math.max(3, pdfProgress)}%` }}
                    />
                  </div>
                  {pdfMode === 'bom' && (
                    <p className="mt-2 text-xs text-blue-600">
                      Large engineering drawings use local AI vision and can take a few minutes — you can leave this tab open.
                    </p>
                  )}
                </div>
              )}

              {pdfError && (
                <div className="mx-4 mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                  <div className="flex items-start gap-2">
                    <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-red-800">Error</p>
                      <p className="text-sm text-red-700 whitespace-pre-line">{pdfError}</p>
                    </div>
                  </div>
                </div>
              )}

              {pdfPreview && (
                <ConvertPreviewPanel
                  accentColor="blue"
                  preview={pdfPreview}
                  onDownload={() => downloadPreviewExcel(pdfPreview)}
                  onReset={() => { setPdfPreview(null); setPdfFile(null); }}
                  onGoCompare={() => setActiveTab('compare')}
                />
              )}
            </div>

            {/* Feature tiles */}
            <div className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-5 bg-white rounded-xl border border-gray-200 shadow-sm lift">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-100 to-blue-200 flex items-center justify-center mb-3 shadow-sm">
                  <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <p className="font-semibold text-gray-900 mb-1">Automatic table detection</p>
                <p className="text-sm text-gray-600">Finds BOM tables even across multi-page engineering drawings.</p>
              </div>
              <div className="p-5 bg-white rounded-xl border border-gray-200 shadow-sm lift">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-indigo-100 to-indigo-200 flex items-center justify-center mb-3 shadow-sm">
                  <svg className="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                  </svg>
                </div>
                <p className="font-semibold text-gray-900 mb-1">Smart column mapping</p>
                <p className="text-sm text-gray-600">Maps to MPN, Qty, Ref Des, Description — no manual cleanup.</p>
              </div>
              <div className="p-5 bg-white rounded-xl border border-gray-200 shadow-sm lift">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-green-100 to-emerald-200 flex items-center justify-center mb-3 shadow-sm">
                  <FileSpreadsheet className="w-5 h-5 text-green-600" />
                </div>
                <p className="font-semibold text-gray-900 mb-1">Clean Excel output</p>
                <p className="text-sm text-gray-600">No merged cells, flat rows — ready for the comparison tool.</p>
              </div>
            </div>

            {/* How-to steps */}
            <div className="mt-10 p-6 bg-gray-50 rounded-xl border border-gray-200">
              <p className="text-center font-semibold text-gray-900 mb-6">How to convert a PDF BOM to Excel</p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-600 to-indigo-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3 shadow-[0_6px_16px_-6px_rgba(79,70,229,0.6)] ring-4 ring-white">1</div>
                  <p className="font-semibold text-gray-900 mb-1">Upload your PDF</p>
                  <p className="text-sm text-gray-600">Drop a digitally generated PDF with a BOM table.</p>
                </div>
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-600 to-indigo-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3 shadow-[0_6px_16px_-6px_rgba(79,70,229,0.6)] ring-4 ring-white">2</div>
                  <p className="font-semibold text-gray-900 mb-1">Click “Convert to Excel”</p>
                  <p className="text-sm text-gray-600">We detect the header row and align columns.</p>
                </div>
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-600 to-indigo-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3 shadow-[0_6px_16px_-6px_rgba(79,70,229,0.6)] ring-4 ring-white">3</div>
                  <p className="font-semibold text-gray-900 mb-1">Download &amp; compare</p>
                  <p className="text-sm text-gray-600">Excel downloads instantly — then switch tabs to compare.</p>
                </div>
              </div>
              <p className="text-xs text-gray-500 text-center mt-6">
                Tip: scanned/image-only PDFs need the Image to Excel tab instead.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ===== TAB 2: Image (JPG/PNG) to Excel Converter ===== */}
      {activeTab === 'image' && (
        <div className="print:hidden">
          <div className="max-w-3xl mx-auto">

            {/* Drop zone card */}
            <div className="card overflow-hidden">
              <div
                {...getRootPropsImage()}
                className={`relative border-2 border-dashed m-4 rounded-xl p-10 text-center cursor-pointer transition-all duration-200 ${
                  isDragActiveImage
                    ? 'border-purple-500 bg-purple-50'
                    : 'border-gray-300 hover:border-purple-400 hover:bg-purple-50/40 surface-subtle'
                }`}
              >
                <input {...getInputPropsImage()} />
                <div className="flex items-center justify-center gap-3 mb-5">
                  <div className="w-14 h-14 rounded-xl bg-purple-100 flex items-center justify-center">
                    <svg className="w-8 h-8 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                  </svg>
                  <div className="w-14 h-14 rounded-xl bg-green-100 flex items-center justify-center">
                    <FileSpreadsheet className="w-8 h-8 text-green-600" />
                  </div>
                </div>
                <p className="text-xl font-semibold text-gray-800 mb-1">
                  {isDragActiveImage ? 'Drop your image here' : 'Drop JPG or PNG here'}
                </p>
                <p className="text-gray-500 mb-3">
                  or click to browse — or just{' '}
                  <kbd className="px-1.5 py-0.5 text-[11px] font-mono bg-white border border-gray-300 rounded shadow-sm">⌘V</kbd>
                  {' / '}
                  <kbd className="px-1.5 py-0.5 text-[11px] font-mono bg-white border border-gray-300 rounded shadow-sm">Ctrl+V</kbd>
                  {' '}to paste a screenshot
                </p>
                <div className="inline-flex items-center gap-2 text-xs text-gray-400">
                  <span className="px-2 py-1 bg-gray-100 rounded">.jpg</span>
                  <span className="px-2 py-1 bg-gray-100 rounded">.jpeg</span>
                  <span className="px-2 py-1 bg-gray-100 rounded">.png</span>
                  <span>· 16 MB max</span>
                </div>
                {imageFile && (
                  <div className="mt-5 inline-flex items-center gap-3 px-4 py-3 bg-white border border-purple-200 rounded-lg shadow-sm">
                    <div className="w-10 h-10 rounded-lg bg-purple-100 flex items-center justify-center">
                      <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <div className="text-left">
                      <p className="font-medium text-gray-900 truncate max-w-xs">{imageFile.name}</p>
                      <p className="text-xs text-gray-500">{(imageFile.size / 1024).toFixed(1)} KB</p>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); setImageFile(null); }}
                      className="ml-2 text-gray-400 hover:text-red-500 transition-colors"
                      aria-label="Remove file"
                    >
                      <XCircle className="w-5 h-5" />
                    </button>
                  </div>
                )}
              </div>

              {/* Thumbnail preview before processing — confirms the user pasted/dropped the right image */}
              {imageFile && <ImageThumbnail file={imageFile} />}

              <div className="px-6 pb-6 pt-2 flex items-center justify-center gap-3 flex-wrap">
                <button
                  onClick={handleImageUpload}
                  disabled={!imageFile || imageProcessing}
                  className="btn-primary px-8 py-3 rounded-xl"
                >
                  {imageProcessing ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current"></div>
                      Converting…
                    </>
                  ) : (
                    <>
                      <FileDown className="w-5 h-5" />
                      Convert to Excel
                    </>
                  )}
                </button>
                <button
                  onClick={async () => {
                    try {
                      const r = await fetch(`${getApiBasePath()}/sample-files`);
                      const data = await r.json();
                      const sample = data.samples?.find((s: any) => s.kind === 'image');
                      if (!sample) { toast('No sample image available', 'error'); return; }
                      const fr = await fetch(`${getApiBasePath()}/sample-files/${encodeURIComponent(sample.name)}`);
                      const blob = await fr.blob();
                      const ext = sample.name.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg';
                      const f = new File([blob], sample.name, { type: ext });
                      setImageFile(f);
                      toast(`Loaded sample ${sample.name}`, 'success');
                    } catch {
                      toast('Could not load sample file', 'error');
                    }
                  }}
                  className="btn-secondary"
                  type="button"
                >
                  Try a sample
                </button>
              </div>

              {imageError && (
                <div className="mx-4 mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                  <div className="flex items-start gap-2">
                    <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-red-800">Error</p>
                      <p className="text-sm text-red-700 whitespace-pre-line">{imageError}</p>
                    </div>
                  </div>
                </div>
              )}

              {imagePreview && (
                <ConvertPreviewPanel
                  accentColor="purple"
                  preview={imagePreview}
                  onDownload={() => downloadPreviewExcel(imagePreview)}
                  onReset={() => { setImagePreview(null); setImageFile(null); }}
                  onGoCompare={() => setActiveTab('compare')}
                />
              )}
            </div>

            {/* Feature tiles */}
            <div className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-5 bg-white rounded-xl border border-gray-200 shadow-sm lift">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-100 to-fuchsia-200 flex items-center justify-center mb-3 shadow-sm">
                  <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <p className="font-semibold text-gray-900 mb-1">OCR-powered extraction</p>
                <p className="text-sm text-gray-600">Tesseract reads text straight from the image — no manual typing.</p>
              </div>
              <div className="p-5 bg-white rounded-xl border border-gray-200 shadow-sm lift">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-100 to-blue-200 flex items-center justify-center mb-3 shadow-sm">
                  <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                  </svg>
                </div>
                <p className="font-semibold text-gray-900 mb-1">Smart column mapping</p>
                <p className="text-sm text-gray-600">Detects MPN, Qty, Ref Des, and Description automatically.</p>
              </div>
              <div className="p-5 bg-white rounded-xl border border-gray-200 shadow-sm lift">
                <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-green-100 to-emerald-200 flex items-center justify-center mb-3 shadow-sm">
                  <FileSpreadsheet className="w-5 h-5 text-green-600" />
                </div>
                <p className="font-semibold text-gray-900 mb-1">Clean Excel output</p>
                <p className="text-sm text-gray-600">Same schema as the PDF tool, ready to feed into BOM Comparison.</p>
              </div>
            </div>

            {/* How-to steps */}
            <div className="mt-10 p-6 bg-gray-50 rounded-xl border border-gray-200">
              <p className="text-center font-semibold text-gray-900 mb-6">How to convert an image BOM to Excel</p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-600 to-pink-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3 shadow-[0_6px_16px_-6px_rgba(168,85,247,0.6)] ring-4 ring-white">1</div>
                  <p className="font-semibold text-gray-900 mb-1">Upload your image</p>
                  <p className="text-sm text-gray-600">Drop a JPG or PNG screenshot of a BOM table.</p>
                </div>
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-600 to-pink-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3 shadow-[0_6px_16px_-6px_rgba(168,85,247,0.6)] ring-4 ring-white">2</div>
                  <p className="font-semibold text-gray-900 mb-1">Click “Convert to Excel”</p>
                  <p className="text-sm text-gray-600">We OCR the image and detect the header row.</p>
                </div>
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-600 to-pink-600 text-white font-bold text-lg flex items-center justify-center mx-auto mb-3 shadow-[0_6px_16px_-6px_rgba(168,85,247,0.6)] ring-4 ring-white">3</div>
                  <p className="font-semibold text-gray-900 mb-1">Download &amp; compare</p>
                  <p className="text-sm text-gray-600">Excel downloads instantly — then switch tabs to compare.</p>
                </div>
              </div>
              <p className="text-xs text-gray-500 text-center mt-6">
                Tip: crop tightly to the table and ensure the image is readable (no blur, even lighting) for best results.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ===== TAB 3: BOM Comparison ===== */}
      {activeTab === 'compare' && (
        <div>

      <div className="controls w-full flex items-center justify-between mb-6 gap-4 print:hidden flex-wrap">
        <div className="flex items-center gap-2">
          <button onClick={clearFiles} className="btn-warning px-5">Start Fresh</button>
        </div>
        <div className="flex justify-end gap-2 flex-wrap">
          <button onClick={handlePrint} className="btn-secondary flex items-center gap-2 px-3 text-sm">
            <Printer className="w-4 h-4" /> Print
          </button>
          <button
            onClick={downloadPdfReport}
            disabled={!results}
            className="btn-secondary flex items-center gap-2 px-3 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            title="One-page PDF summary suitable for emailing"
          >
            <FileDown className="w-4 h-4" /> PDF report
          </button>
          <button
            onClick={exportRenamedCsv}
            disabled={!results || !results.modified_parts.some(p => p.MPN_Changed)}
            className="btn-secondary flex items-center gap-2 px-3 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            title="Export AI-detected MPN rename pairs as CSV (editable, re-importable as aliases)"
          >
            <FileDown className="w-4 h-4" /> Rename pairs CSV
          </button>
          <button
            onClick={() => setTemplateExportOpen(true)}
            disabled={!file1 || !file2 || !selectedColumns.file1.mpn}
            className="btn-secondary flex items-center gap-2 px-3 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
            title="Export one file's data wrapped in the other file's header + styling"
          >
            <FileDown className="w-4 h-4" /> Export in template
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
                  <div className="flex-1">
                    <p className="font-medium text-success-800">{fileName1}</p>
                    <p className="text-sm text-success-600">
                      {(file1.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  {revInfo.file1 && (
                    <span className="px-2 py-1 text-[11px] font-bold rounded-full bg-blue-100 text-blue-800 border border-blue-200" title="Revision detected from filename or header">
                      Rev {revInfo.file1}
                    </span>
                  )}
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
                  <div className="flex-1">
                    <p className="font-medium text-success-800">{fileName2}</p>
                    <p className="text-sm text-success-600">
                      {(file2.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  {revInfo.file2 && (
                    <span className="px-2 py-1 text-[11px] font-bold rounded-full bg-green-100 text-green-800 border border-green-200" title="Revision detected from filename or header">
                      Rev {revInfo.file2}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Revision delta banner — shown when both files have detected revs */}
      {revInfo.file1 && revInfo.file2 && (
        <div className="mb-6 px-4 py-2 bg-gradient-to-r from-blue-50 to-green-50 border border-blue-200 rounded-lg text-sm flex items-center gap-3 print:hidden">
          <span className="font-semibold text-blue-700">Revision delta:</span>
          <span className="font-mono">Rev {revInfo.file1}</span>
          <span className="text-gray-400">→</span>
          <span className="font-mono">Rev {revInfo.file2}</span>
          <span className="ml-auto text-xs text-gray-500">Auto-detected from filename + workbook header</span>
        </div>
      )}

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
    </AppShell>
  );
}

// ─────────────────────────────────────────────────────────────────────
// App shell, navigation, theme toggle, processing overlay
// ─────────────────────────────────────────────────────────────────────

type Tab = 'pdf' | 'image' | 'compare';

function AppShell({
  children,
  activeTab,
  setActiveTab,
  onOpenSettings,
  onOpenHelp,
}: {
  children: React.ReactNode;
  activeTab: Tab;
  setActiveTab: (t: Tab) => void;
  onOpenSettings?: () => void;
  onOpenHelp?: () => void;
}) {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (typeof document !== 'undefined') {
      setTheme(document.documentElement.classList.contains('dark') ? 'dark' : 'light');
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    if (next === 'dark') document.documentElement.classList.add('dark');
    else document.documentElement.classList.remove('dark');
    try { localStorage.setItem('theme', next); } catch {}
  };

  const navItems: { key: Tab; label: string; description: string; icon: React.ReactNode }[] = [
    {
      key: 'pdf',
      label: 'PDF to Excel',
      description: 'Extract tables from PDFs',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      ),
    },
    {
      key: 'image',
      label: 'Image to Excel',
      description: 'OCR JPG / PNG screenshots',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      ),
    },
    {
      key: 'compare',
      label: 'BOM Comparison',
      description: 'Diff two Excel BOMs',
      icon: <ArrowLeftRight className="w-5 h-5" strokeWidth={1.8} />,
    },
  ];

  return (
    <div className="min-h-screen flex">
      {/* Sidebar — desktop */}
      <aside className="app-sidebar hidden lg:flex flex-col w-64 shrink-0 border-r border-app surface print:hidden">
        <div className="px-5 py-5 flex items-center gap-3">
          {/* Brand mark — full-color SVG. Replaces the generic spreadsheet glyph
              with the Tool Suite's signature crossed-cards + AI spark logo. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/toolsuite-logo.svg" alt="Tool Suite" width={40} height={40} className="w-10 h-10 rounded-xl shadow-pop" />
          <div className="leading-tight">
            <p className="font-semibold text-app">Tool Suite</p>
            <p className="text-[11px] text-app-subtle uppercase tracking-wider">American Circuits</p>
          </div>
        </div>

        <div className="px-3 py-2">
          <p className="px-2 mb-1 text-[11px] font-semibold uppercase tracking-wider text-app-subtle">Tools</p>
          <nav className="flex flex-col gap-1">
            {navItems.map(it => (
              <button
                key={it.key}
                onClick={() => setActiveTab(it.key)}
                className={`nav-item text-left ${activeTab === it.key ? 'nav-item-active' : ''}`}
              >
                <span className="shrink-0">{it.icon}</span>
                <span className="flex flex-col">
                  <span>{it.label}</span>
                  <span className="text-[11px] text-app-subtle font-normal">{it.description}</span>
                </span>
              </button>
            ))}
          </nav>
        </div>

        <RecentConversions onOpenCompare={() => setActiveTab('compare')} />

        {/* Secondary actions: settings + help */}
        <div className="px-3 mt-3 flex flex-col gap-1">
          <button onClick={onOpenSettings} className="nav-item text-left">
            <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><circle cx="12" cy="12" r="3"/>
            </svg>
            <span>Settings</span>
          </button>
          <button onClick={onOpenHelp} className="nav-item text-left">
            <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10"/><path strokeLinecap="round" strokeLinejoin="round" d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01"/>
            </svg>
            <span>Help & shortcuts</span>
          </button>
        </div>

        <div className="mt-auto px-3 py-3 border-t border-app">
          <button onClick={toggleTheme} className="btn-ghost w-full justify-start">
            {theme === 'dark' ? (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" /><path strokeLinecap="round" d="M12 2v2m0 16v2m10-10h-2M4 12H2m15.5-6.5l-1.4 1.4M7.9 16.1l-1.4 1.4m0-11l1.4 1.4m8.2 8.2l1.4 1.4" /></svg>
                Light mode
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" /></svg>
                Dark mode
              </>
            )}
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="lg:hidden fixed top-0 inset-x-0 z-40 surface border-b border-app print:hidden">
        <div className="flex items-center justify-between px-4 h-14">
          <div className="flex items-center gap-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/toolsuite-logo.svg" alt="Tool Suite" width={28} height={28} className="w-7 h-7 rounded-lg" />
            <span className="font-semibold text-app">Tool Suite</span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={toggleTheme} className="btn-ghost px-2">
              {theme === 'dark' ? '☀' : '☾'}
            </button>
            <button onClick={() => setMobileNavOpen(o => !o)} className="btn-ghost px-2">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" /></svg>
            </button>
          </div>
        </div>
      </div>

      {/* Mobile slide-over drawer with backdrop */}
      {mobileNavOpen && (
        <div className="lg:hidden fixed inset-0 z-50 print:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-up"
            onClick={() => setMobileNavOpen(false)}
          />
          {/* Drawer */}
          <aside className="absolute left-0 top-0 h-full w-72 surface border-r border-app flex flex-col animate-fade-up">
            <div className="flex items-center justify-between px-5 py-5 border-b border-app">
              <div className="flex items-center gap-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/toolsuite-logo.svg" alt="Tool Suite" width={32} height={32} className="w-8 h-8 rounded-xl" />
                <p className="font-semibold text-app">Tool Suite</p>
              </div>
              <button onClick={() => setMobileNavOpen(false)} className="btn-ghost px-2" aria-label="Close menu">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
            <div className="px-3 py-3">
              <p className="px-2 mb-1 text-[11px] font-semibold uppercase tracking-wider text-app-subtle">Tools</p>
              <nav className="flex flex-col gap-1">
                {navItems.map(it => (
                  <button
                    key={it.key}
                    onClick={() => { setActiveTab(it.key); setMobileNavOpen(false); }}
                    className={`nav-item text-left ${activeTab === it.key ? 'nav-item-active' : ''}`}
                  >
                    <span className="shrink-0">{it.icon}</span>
                    <span className="flex flex-col">
                      <span>{it.label}</span>
                      <span className="text-[11px] text-app-subtle font-normal">{it.description}</span>
                    </span>
                  </button>
                ))}
              </nav>
            </div>
            <div className="px-3 mt-2 flex flex-col gap-1 border-t border-app pt-3">
              <button onClick={() => { setMobileNavOpen(false); onOpenSettings?.(); }} className="nav-item text-left">
                <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><circle cx="12" cy="12" r="3"/></svg>
                Settings
              </button>
              <button onClick={() => { setMobileNavOpen(false); onOpenHelp?.(); }} className="nav-item text-left">
                <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path strokeLinecap="round" strokeLinejoin="round" d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01"/></svg>
                Help & shortcuts
              </button>
            </div>
            <div className="mt-auto px-3 py-3 border-t border-app">
              <button onClick={toggleTheme} className="btn-ghost w-full justify-start">
                {theme === 'dark' ? '☀ Light mode' : '☾ Dark mode'}
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* Main */}
      <main className="flex-1 min-w-0 lg:pt-0 pt-16 print:pt-0">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-10">
          {children}
        </div>
      </main>
    </div>
  );
}

function SectionHeader({ activeTab }: { activeTab: Tab }) {
  const meta: Record<Tab, { title: string; sub: string; pill: string }> = {
    pdf:     { title: 'PDF to Excel',     sub: 'Drop a digitally-generated PDF — we extract the table and map BOM columns automatically.', pill: 'AI column detection' },
    image:   { title: 'Image to Excel',   sub: 'OCR a JPG or PNG of any table. Paste with ⌘V/Ctrl+V or drop a file.', pill: 'Tesseract + smart whitelisting' },
    compare: { title: 'BOM Comparison',   sub: 'Diff two Excel BOMs. Fuzzy matching catches renamed MPNs across revisions.', pill: 'Fuzzy MPN matching' },
  };
  const m = meta[activeTab];
  return (
    <div className="mb-8 print:hidden animate-fade-up">
      <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wider bg-[var(--accent-soft)] text-[var(--accent)] border border-[var(--accent-border)]">
        <span className="w-1.5 h-1.5 rounded-full bg-current" /> {m.pill}
      </div>
      <h1 className="mt-3 text-3xl sm:text-4xl font-bold text-app">{m.title}</h1>
      <p className="mt-2 text-app-muted text-base sm:text-lg max-w-2xl">{m.sub}</p>
    </div>
  );
}

function ProcessingOverlay({ phase }: { phase: 'pdf' | 'image' | 'compare' }) {
  const stepsByPhase: Record<typeof phase, string[]> = {
    pdf:     ['Reading PDF', 'Detecting tables', 'Mapping columns', 'Cleaning data', 'Generating Excel'],
    image:   ['Loading image', 'Deskewing & sharpening', 'OCR with column whitelists', 'Building rows', 'Generating Excel'],
    compare: ['Reading both files', 'Detecting columns', 'Building MPN sets', 'Fuzzy matching renamed parts', 'Diffing fields'],
  };
  const steps = stepsByPhase[phase];
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm bg-black/30 print:hidden animate-fade-up">
      <div className="card p-6 max-w-md w-[90%]">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-xl bg-[var(--accent-soft)] flex items-center justify-center">
            <svg className="w-5 h-5 animate-spin" style={{ color: 'var(--accent)' }} fill="none" viewBox="0 0 24 24">
              <circle className="opacity-30" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v3a5 5 0 00-5 5H4z" />
            </svg>
          </div>
          <div>
            <p className="font-semibold text-app">Processing…</p>
            <p className="text-xs text-app-subtle">This usually takes a few seconds.</p>
          </div>
        </div>
        <ol className="space-y-2.5">
          {steps.map((s, i) => (
            <li key={s} className="flex items-center gap-3">
              <span className="w-5 h-5 rounded-full bg-[var(--surface-inset)] text-app-subtle text-[11px] font-semibold flex items-center justify-center">
                {i + 1}
              </span>
              <span className="text-sm text-app-muted flex-1">{s}</span>
            </li>
          ))}
        </ol>
        <div className="mt-5 h-1 rounded-full bg-[var(--surface-inset)] overflow-hidden">
          <div className="h-full animate-step-bar rounded-full" style={{ background: 'var(--accent)' }} />
        </div>
      </div>
    </div>
  );
}

type RecentItem = { ts: number; kind: 'pdf' | 'image' | 'compare'; label: string };

function RecentConversions({ onOpenCompare }: { onOpenCompare: () => void }) {
  const [items, setItems] = useState<RecentItem[]>([]);
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('toolsuite.recents');
      if (raw) setItems(JSON.parse(raw).slice(0, 5));
    } catch {}
    const onChange = () => {
      try {
        const raw = sessionStorage.getItem('toolsuite.recents');
        setItems(raw ? JSON.parse(raw).slice(0, 5) : []);
      } catch {}
    };
    window.addEventListener('toolsuite-recents-updated', onChange);
    return () => window.removeEventListener('toolsuite-recents-updated', onChange);
  }, []);

  if (!items.length) return null;
  const iconFor = (k: RecentItem['kind']) =>
    k === 'pdf' ? '📄' : k === 'image' ? '🖼' : '⇄';

  return (
    <div className="px-3 mt-2">
      <p className="px-2 mb-1 text-[11px] font-semibold uppercase tracking-wider text-app-subtle">Recent</p>
      <ul className="flex flex-col gap-0.5">
        {items.map(it => (
          <li key={it.ts}>
            <div className="flex items-center gap-2 px-2 py-1.5 rounded-md text-xs text-app-muted hover:bg-[var(--surface-subtle)] transition-colors truncate" title={it.label}>
              <span className="text-base leading-none">{iconFor(it.kind)}</span>
              <span className="truncate flex-1">{it.label}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function pushRecent(item: Omit<RecentItem, 'ts'>) {
  try {
    const raw = sessionStorage.getItem('toolsuite.recents');
    const prev: RecentItem[] = raw ? JSON.parse(raw) : [];
    const next: RecentItem[] = [{ ...item, ts: Date.now() }, ...prev].slice(0, 10);
    sessionStorage.setItem('toolsuite.recents', JSON.stringify(next));
    window.dispatchEvent(new Event('toolsuite-recents-updated'));
  } catch {}
}

// ────────────────────────────────────────────────────────────────────
// Toasts, Settings drawer, Help drawer
// ────────────────────────────────────────────────────────────────────

function ToastRack({ toasts, onDismiss }: { toasts: { id: number; kind: 'success'|'error'|'info'; msg: string }[]; onDismiss: (id: number) => void }) {
  if (!toasts.length) return null;
  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 print:hidden">
      {toasts.map(t => (
        <div key={t.id} role="status"
          className={`min-w-[260px] max-w-sm card px-4 py-3 flex items-start gap-3 animate-fade-up shadow-pop ${
            t.kind === 'success' ? 'border-emerald-300 dark:border-emerald-700' :
            t.kind === 'error' ? 'border-rose-300 dark:border-rose-700' :
            'border-app'
          }`}>
          <span className="mt-0.5">
            {t.kind === 'success' ? '✓' : t.kind === 'error' ? '✗' : 'ⓘ'}
          </span>
          <span className="flex-1 text-sm text-app">{t.msg}</span>
          <button onClick={() => onDismiss(t.id)} className="text-app-subtle hover:text-app">✕</button>
        </div>
      ))}
    </div>
  );
}

type AliasPairRec = { mpn_a: string; mpn_b: string; note?: string; created_at?: string };
type AuditEventRec = {
  id: string; timestamp: string; kind: string;
  file1?: { name: string; sha256: string };
  file2?: { name: string; sha256: string };
  summary?: Record<string, any>;
  revision?: { file1?: string | null; file2?: string | null };
};

function SettingsDrawer({
  onClose, fuzzyThreshold, setFuzzyThreshold, ignoredPairs, onClearIgnored,
  aliasPairs, aliasLoading, onLoadAliases, onAddAlias, onRemoveAlias, onImportRenamedCsv,
  auditEvents, onLoadAudit, onClearAudit,
}: {
  onClose: () => void;
  fuzzyThreshold: number;
  setFuzzyThreshold: (v: number) => void;
  ignoredPairs: [string, string][];
  onClearIgnored: () => void;
  aliasPairs: AliasPairRec[];
  aliasLoading: boolean;
  onLoadAliases: () => void;
  onAddAlias: (a: string, b: string, note?: string) => Promise<boolean>;
  onRemoveAlias: (a: string, b: string) => void;
  onImportRenamedCsv: (file: File) => Promise<void>;
  auditEvents: AuditEventRec[];
  onLoadAudit: () => void;
  onClearAudit: () => void;
}) {
  const [newA, setNewA] = useState('');
  const [newB, setNewB] = useState('');
  const [newNote, setNewNote] = useState('');
  const [adding, setAdding] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => { onLoadAliases(); onLoadAudit(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="fixed inset-0 z-[80] flex justify-end print:hidden">
      <div className="absolute inset-0 bg-black/40 animate-fade-up" onClick={onClose} />
      <aside className="relative w-full max-w-md surface border-l border-app shadow-pop overflow-y-auto animate-fade-up">
        <header className="px-6 py-5 border-b border-app flex items-center justify-between">
          <h2 className="text-lg font-bold text-app">Settings</h2>
          <button onClick={onClose} className="btn-ghost px-2">✕</button>
        </header>
        <div className="p-6 space-y-6">
          <section>
            <h3 className="font-semibold text-app mb-2">Fuzzy MPN match threshold</h3>
            <p className="text-sm text-app-muted mb-4">
              How similar two MPNs must be for the comparison tool to flag them
              as the same physical part across BOMs. Lower = more aggressive
              matching (catches typos and suffixes), higher = stricter.
            </p>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={0.5}
                max={1}
                step={0.01}
                value={fuzzyThreshold}
                onChange={e => setFuzzyThreshold(parseFloat(e.target.value))}
                className="flex-1 accent-indigo-500"
                aria-label="Fuzzy match threshold"
              />
              <span className="font-mono text-sm tabular-nums text-app w-14 text-right">
                {Math.round(fuzzyThreshold * 100)}%
              </span>
            </div>
            <div className="mt-2 flex gap-2 text-xs text-app-subtle">
              <button onClick={() => setFuzzyThreshold(0.78)} className="btn-ghost px-2 py-1 text-xs">Loose 78%</button>
              <button onClick={() => setFuzzyThreshold(0.88)} className="btn-ghost px-2 py-1 text-xs">Default 88%</button>
              <button onClick={() => setFuzzyThreshold(0.95)} className="btn-ghost px-2 py-1 text-xs">Strict 95%</button>
            </div>
          </section>

          <section>
            <h3 className="font-semibold text-app mb-2">Rejected MPN pairs</h3>
            <p className="text-sm text-app-muted mb-3">
              Pairs you&apos;ve manually marked as <em>not</em> the same part. The
              comparison tool will skip these even if their similarity passes
              the threshold.
            </p>
            {ignoredPairs.length === 0 ? (
              <p className="text-sm text-app-subtle italic">No rejected pairs yet. Reject a fuzzy match from the comparison results to add one.</p>
            ) : (
              <ul className="surface-subtle rounded-lg p-3 max-h-64 overflow-y-auto text-sm font-mono space-y-1.5">
                {ignoredPairs.map(([a, b], i) => (
                  <li key={i} className="flex items-center justify-between gap-2">
                    <span className="text-rose-500 truncate">{a}</span>
                    <span className="text-app-subtle">↔</span>
                    <span className="text-emerald-500 truncate">{b}</span>
                  </li>
                ))}
              </ul>
            )}
            {ignoredPairs.length > 0 && (
              <button onClick={onClearIgnored} className="btn-secondary mt-3 text-xs">Clear all rejected pairs</button>
            )}
          </section>

          <section>
            <h3 className="font-semibold text-app mb-2">MPN cross-references</h3>
            <p className="text-sm text-app-muted mb-3">
              Mark two MPNs as the same physical part (e.g. Yageo ↔ Vishay
              equivalents, internal part numbers ↔ vendor part numbers).
              During comparison, paired MPNs are folded into &quot;renamed&quot;
              instead of being flagged as separate Add+Remove.
            </p>
            <div className="grid grid-cols-1 gap-2 mb-3">
              <input
                type="text"
                placeholder="MPN A"
                value={newA}
                onChange={e => setNewA(e.target.value)}
                className="px-3 py-2 surface-inset border border-app rounded-lg text-sm font-mono"
              />
              <input
                type="text"
                placeholder="MPN B"
                value={newB}
                onChange={e => setNewB(e.target.value)}
                className="px-3 py-2 surface-inset border border-app rounded-lg text-sm font-mono"
              />
              <input
                type="text"
                placeholder="Note (optional, e.g. 'Yageo cross-ref')"
                value={newNote}
                onChange={e => setNewNote(e.target.value)}
                className="px-3 py-2 surface-inset border border-app rounded-lg text-sm"
              />
              <div className="flex gap-2">
                <button
                  onClick={async () => {
                    if (!newA.trim() || !newB.trim()) return;
                    setAdding(true);
                    const ok = await onAddAlias(newA.trim(), newB.trim(), newNote.trim());
                    setAdding(false);
                    if (ok) { setNewA(''); setNewB(''); setNewNote(''); }
                  }}
                  disabled={adding || !newA.trim() || !newB.trim()}
                  className="btn-primary text-xs flex-1 disabled:opacity-40"
                >
                  {adding ? 'Adding…' : 'Add cross-reference'}
                </button>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="btn-secondary text-xs"
                  title="Import cross-references from a CSV (mpn_a,mpn_b,note)"
                >
                  Import CSV
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (f) await onImportRenamedCsv(f);
                    if (fileInputRef.current) fileInputRef.current.value = '';
                  }}
                />
              </div>
            </div>
            {aliasLoading ? (
              <p className="text-sm text-app-subtle">Loading…</p>
            ) : aliasPairs.length === 0 ? (
              <p className="text-sm text-app-subtle italic">No cross-references saved yet.</p>
            ) : (
              <ul className="surface-subtle rounded-lg p-3 max-h-72 overflow-y-auto text-sm space-y-2">
                {aliasPairs.map((p, i) => (
                  <li key={i} className="flex items-center justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="font-mono text-xs truncate">
                        <span className="text-blue-600">{p.mpn_a}</span>
                        <span className="text-app-subtle mx-1">↔</span>
                        <span className="text-emerald-600">{p.mpn_b}</span>
                      </p>
                      {p.note && <p className="text-xs text-app-subtle truncate">{p.note}</p>}
                    </div>
                    <button
                      onClick={() => onRemoveAlias(p.mpn_a, p.mpn_b)}
                      className="text-xs text-rose-500 hover:text-rose-700"
                      title="Remove this cross-reference"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="font-semibold text-app mb-2">Comparison history (audit trail)</h3>
            <p className="text-sm text-app-muted mb-3">
              Server-side log of all comparisons run. File hashes (SHA-256) are
              stored so the same comparison is traceable later. Cleared on
              demand.
            </p>
            {auditEvents.length === 0 ? (
              <p className="text-sm text-app-subtle italic">No history yet.</p>
            ) : (
              <ul className="surface-subtle rounded-lg p-3 max-h-72 overflow-y-auto text-xs space-y-3">
                {auditEvents.map(ev => (
                  <li key={ev.id} className="border-b border-app pb-2 last:border-0 last:pb-0">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-app-subtle">{new Date(ev.timestamp).toLocaleString()}</span>
                      <span className="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-[10px]">{ev.kind}</span>
                    </div>
                    <div className="mt-1">
                      <p className="truncate"><strong>F1:</strong> {ev.file1?.name} {ev.revision?.file1 ? <em>(Rev {ev.revision.file1})</em> : null}</p>
                      <p className="truncate"><strong>F2:</strong> {ev.file2?.name} {ev.revision?.file2 ? <em>(Rev {ev.revision.file2})</em> : null}</p>
                      {ev.summary && (
                        <p className="text-app-subtle mt-1">
                          {ev.summary.unchanged_parts_count ?? 0} unchanged · {ev.summary.modified_parts_count ?? 0} mod · {ev.summary.new_parts_count ?? 0} add · {ev.summary.removed_parts_count ?? 0} rem
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex gap-2 mt-3">
              <button onClick={onLoadAudit} className="btn-secondary text-xs">Refresh</button>
              {auditEvents.length > 0 && (
                <button onClick={onClearAudit} className="btn-secondary text-xs">Clear history</button>
              )}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}

function TemplateExportModal({
  fileName1, fileName2, revInfo, direction, setDirection, tint, setTint, loading, onClose, onExport,
}: {
  fileName1: string;
  fileName2: string;
  revInfo: { file1?: string | null; file2?: string | null };
  direction: 'file2-into-file1' | 'file1-into-file2';
  setDirection: (d: 'file2-into-file1' | 'file1-into-file2') => void;
  tint: boolean;
  setTint: (v: boolean) => void;
  loading: boolean;
  onClose: () => void;
  onExport: () => void;
}) {
  const templateName = direction === 'file2-into-file1' ? fileName1 : fileName2;
  const dataName = direction === 'file2-into-file1' ? fileName2 : fileName1;
  const templateRev = direction === 'file2-into-file1' ? revInfo.file1 : revInfo.file2;
  const dataRev = direction === 'file2-into-file1' ? revInfo.file2 : revInfo.file1;
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center print:hidden">
      <div className="absolute inset-0 bg-black/50 animate-fade-up" onClick={loading ? undefined : onClose} />
      <div className="relative w-full max-w-lg mx-4 surface border border-app rounded-2xl shadow-pop animate-fade-up">
        <header className="px-6 py-4 border-b border-app flex items-center justify-between">
          <h2 className="text-lg font-bold text-app">Export in original template</h2>
          <button onClick={onClose} disabled={loading} className="btn-ghost px-2 disabled:opacity-40">✕</button>
        </header>
        <div className="p-6 space-y-5">
          <p className="text-sm text-app-muted">
            Re-render one file&apos;s data inside the other file&apos;s header,
            column order, styling, and title block. Useful when the customer
            sent you their BOM in their format and you want to send the
            updated parts back in the same template.
          </p>

          <div>
            <p className="font-semibold text-app text-sm mb-2">Direction</p>
            <div className="space-y-2">
              <label className="flex items-start gap-3 p-3 surface-inset rounded-lg cursor-pointer">
                <input
                  type="radio"
                  checked={direction === 'file2-into-file1'}
                  onChange={() => setDirection('file2-into-file1')}
                  className="mt-1"
                />
                <div className="flex-1 text-sm">
                  <p className="font-medium text-app">File 2 data → File 1 template</p>
                  <p className="text-app-muted text-xs mt-0.5">
                    Use <strong>{fileName1 || 'File 1'}</strong>{templateRev && direction === 'file2-into-file1' ? <em> (Rev {templateRev})</em> : null} as the template; fill it with rows from <strong>{fileName2 || 'File 2'}</strong>{dataRev && direction === 'file2-into-file1' ? <em> (Rev {dataRev})</em> : null}.
                  </p>
                </div>
              </label>
              <label className="flex items-start gap-3 p-3 surface-inset rounded-lg cursor-pointer">
                <input
                  type="radio"
                  checked={direction === 'file1-into-file2'}
                  onChange={() => setDirection('file1-into-file2')}
                  className="mt-1"
                />
                <div className="flex-1 text-sm">
                  <p className="font-medium text-app">File 1 data → File 2 template</p>
                  <p className="text-app-muted text-xs mt-0.5">
                    Use <strong>{fileName2 || 'File 2'}</strong>{templateRev && direction === 'file1-into-file2' ? <em> (Rev {templateRev})</em> : null} as the template; fill it with rows from <strong>{fileName1 || 'File 1'}</strong>{dataRev && direction === 'file1-into-file2' ? <em> (Rev {dataRev})</em> : null}.
                  </p>
                </div>
              </label>
            </div>
          </div>

          <label className="flex items-center gap-3 p-3 surface-inset rounded-lg cursor-pointer">
            <input
              type="checkbox"
              checked={tint}
              onChange={e => setTint(e.target.checked)}
            />
            <div className="text-sm">
              <p className="font-medium text-app">Tint changed cells</p>
              <p className="text-app-muted text-xs mt-0.5">
                Amber = qty changed · indigo = ref des changed · violet = description changed · green = added · rose = removed.
              </p>
            </div>
          </label>

          <div className="text-xs text-app-subtle bg-amber-50 border border-amber-200 rounded-lg p-3">
            <strong>Heads up:</strong> if the template file is a legacy <code>.xls</code>,
            we convert it to <code>.xlsx</code> first — fonts, fills and borders will be
            simplified. Use an <code>.xlsx</code> template for best fidelity.
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button onClick={onClose} disabled={loading} className="btn-secondary disabled:opacity-40">Cancel</button>
            <button onClick={onExport} disabled={loading} className="btn-primary disabled:opacity-40">
              {loading ? 'Exporting…' : 'Export'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ImageThumbnail({ file }: { file: File }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  if (!url) return null;
  return (
    <div className="px-6 pb-2">
      <p className="text-xs text-app-subtle mb-2">Preview · {(file.size / 1024).toFixed(1)} KB</p>
      <div className="rounded-lg overflow-hidden border border-app surface-subtle inline-block max-w-full">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={file.name} className="max-h-48 object-contain" />
      </div>
    </div>
  );
}

function RenamedPartsPanel({
  parts, fileName1, fileName2, onReject,
}: {
  parts: ModifiedPart[];
  fileName1: string;
  fileName2: string;
  onReject: (a: string, b: string) => void;
}) {
  if (!parts.length) {
    return (
      <div className="card p-8 text-center text-app-muted">
        <div className="w-14 h-14 mx-auto rounded-2xl bg-[var(--accent-soft)] flex items-center justify-center mb-3">
          <span className="text-2xl">✓</span>
        </div>
        <p className="font-semibold text-app">No renamed MPNs detected.</p>
        <p className="text-sm mt-1">The fuzzy matcher didn&apos;t find any near-miss MPN pairs across these files.</p>
      </div>
    );
  }
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-4 border-b border-app">
        <h3 className="font-semibold text-app">Likely renamed parts</h3>
        <p className="text-sm text-app-muted mt-1">
          The AI thinks these MPN strings refer to the same physical part across files.
          Reject any pair that&apos;s actually two different parts — it&apos;ll be excluded from
          future comparisons.
        </p>
      </div>
      <div className="divide-y divide-[var(--surface-border)]">
        {parts.map((p, i) => (
          <div key={i} className="px-5 py-4 flex flex-wrap items-center gap-4">
            <div className="flex-1 min-w-[200px]">
              <p className="text-[11px] uppercase tracking-wider text-app-subtle mb-1">{fileName1 || 'File 1'}</p>
              <p className="font-mono text-sm text-rose-500 line-through">{p['File1 MPN']}</p>
            </div>
            <span className="text-app-subtle">→</span>
            <div className="flex-1 min-w-[200px]">
              <p className="text-[11px] uppercase tracking-wider text-app-subtle mb-1">{fileName2 || 'File 2'}</p>
              <p className="font-mono text-sm text-emerald-500">{p['File2 MPN']}</p>
            </div>
            <button
              onClick={() => onReject(p['File1 MPN'] || '', p['File2 MPN'] || '')}
              className="btn-secondary text-xs"
              title="Mark these MPNs as not the same part"
            >
              Not the same part
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function DescriptionDriftPanel({ parts }: { parts: any[] }) {
  if (!parts.length) {
    return <div className="card p-6 text-app-muted text-sm">No description drift detected.</div>;
  }
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-4 border-b border-app">
        <h3 className="font-semibold text-app">Description drift</h3>
        <p className="text-sm text-app-muted mt-1">
          Same MPN, but the description text changed substantially. Often indicates
          a packaging or spec note update worth reviewing.
        </p>
      </div>
      <div className="divide-y divide-[var(--surface-border)] max-h-[600px] overflow-y-auto">
        {parts.map((p, i) => (
          <div key={i} className="px-5 py-4">
            <p className="font-mono text-sm font-semibold text-app mb-2">{p.MPN}</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              <div className="surface-subtle rounded-lg p-3">
                <p className="text-[11px] uppercase tracking-wider text-app-subtle mb-1">Before</p>
                <p className="text-app-muted whitespace-pre-wrap">{p['File1 Description']}</p>
              </div>
              <div className="surface-subtle rounded-lg p-3">
                <p className="text-[11px] uppercase tracking-wider text-app-subtle mb-1">After</p>
                <p className="text-app-muted whitespace-pre-wrap">{p['File2 Description']}</p>
              </div>
            </div>
            {p['Description Similarity'] !== undefined && (
              <p className="mt-2 text-xs text-app-subtle">Similarity: {Math.round(parseFloat(p['Description Similarity']) * 100)}%</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DuplicateMpnPanel({ warnings }: { warnings: any[] }) {
  if (!warnings.length) {
    return <div className="card p-6 text-app-muted text-sm">No duplicate MPNs detected.</div>;
  }
  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-4 border-b border-app">
        <h3 className="font-semibold text-app">Duplicate MPNs in source files</h3>
        <p className="text-sm text-app-muted mt-1">
          The same MPN appears more than once in one of the source files. Only the
          first occurrence is used for comparison; subsequent rows are silently
          skipped. Clean these up in the source file for accurate diffs.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="surface-subtle">
              <th className="px-4 py-2 text-left font-semibold text-app">File</th>
              <th className="px-4 py-2 text-left font-semibold text-app">MPN</th>
              <th className="px-4 py-2 text-left font-semibold text-app">Occurrences</th>
              <th className="px-4 py-2 text-left font-semibold text-app">Lines</th>
            </tr>
          </thead>
          <tbody>
            {warnings.map((w, i) => (
              <tr key={i} className="border-t border-app">
                <td className="px-4 py-2 text-app-muted">{w.file}</td>
                <td className="px-4 py-2 font-mono text-app">{w.mpn}</td>
                <td className="px-4 py-2 text-app">{w.occurrences}</td>
                <td className="px-4 py-2 font-mono text-xs text-app-muted">{Array.isArray(w.lines) ? w.lines.join(', ') : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HelpDrawer({ onClose }: { onClose: () => void }) {
  const shortcuts: [string, string][] = [
    ['/', 'Focus the search bar'],
    ['g 1', 'Go to PDF to Excel'],
    ['g 2', 'Go to Image to Excel'],
    ['g 3', 'Go to BOM Comparison'],
    ['?', 'Toggle this help drawer'],
    ['Esc', 'Close any open drawer or modal'],
    ['⌘V / Ctrl+V', 'Paste a screenshot on the Image tab'],
  ];
  return (
    <div className="fixed inset-0 z-[80] flex justify-end print:hidden">
      <div className="absolute inset-0 bg-black/40 animate-fade-up" onClick={onClose} />
      <aside className="relative w-full max-w-md surface border-l border-app shadow-pop overflow-y-auto animate-fade-up">
        <header className="px-6 py-5 border-b border-app flex items-center justify-between">
          <h2 className="text-lg font-bold text-app">Help & shortcuts</h2>
          <button onClick={onClose} className="btn-ghost px-2">✕</button>
        </header>
        <div className="p-6 space-y-6">
          <section>
            <h3 className="font-semibold text-app mb-3">Keyboard shortcuts</h3>
            <ul className="space-y-2">
              {shortcuts.map(([keys, desc]) => (
                <li key={keys} className="flex items-center justify-between text-sm">
                  <span className="text-app-muted">{desc}</span>
                  <kbd className="px-2 py-1 text-[11px] font-mono surface-inset border border-app rounded">{keys}</kbd>
                </li>
              ))}
            </ul>
          </section>

          <section className="space-y-3 text-sm text-app-muted">
            <h3 className="font-semibold text-app">How the AI works</h3>
            <p>
              The Tool Suite runs all extraction locally — Tesseract OCR for images,
              pdfplumber for PDFs, plus rapidfuzz for column classification and MPN
              matching. There&apos;s no external LLM call. Confidence badges show how
              sure the local pipeline is. Click the badge to see per-column scores.
            </p>
            <p>
              Comparisons use a fuzzy MPN matcher to catch renamed parts across
              revisions (<code className="text-xs">BC547</code> ↔
              <code className="text-xs"> BC547BTA</code>). Adjust the threshold in
              Settings — or manually reject pairs that aren&apos;t actually the same.
            </p>
          </section>
        </div>
      </aside>
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
