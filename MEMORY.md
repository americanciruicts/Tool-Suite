# BOM Comparison Tool - Project Memory

## Project Overview
**Project Name**: BOM Comparison Tool  
**Version**: 1.1 
**Repository**: excel_tool_backup  
**Primary Purpose**: Modern BOM (Bill of Materials) comparison tool that intelligently compares Excel files and identifies differences between parts, quantities, and reference designators.

## Architecture & Technology Stack

### Frontend (Next.js 14)
- **Framework**: Next.js 14.0.4 with React 18.2.0
- **Language**: TypeScript 5.3.3
- **Styling**: Tailwind CSS 3.3.6 with custom design system
- **UI Components**: Custom components with Lucide React icons
- **File Upload**: react-dropzone for drag-and-drop Excel file uploads
- **Excel Processing**: xlsx and exceljs libraries for client-side Excel handling
- **HTTP Client**: axios for API communication

### Backend (FastAPI)
- **Framework**: FastAPI (Python 3.11)
- **Web Server**: uvicorn with ASGI
- **Excel Processing**: pandas, openpyxl, xlrd for server-side Excel parsing
- **CORS**: Configured for cross-origin requests (supports ngrok and any domain)
- **API Endpoints**:
  - `GET /` - Root endpoint
  - `GET /health` - Health check
  - `POST /api/compare` - Main BOM comparison endpoint
  - `GET /api/test` - Test endpoint

### Database & Infrastructure
- **Database**: PostgreSQL 15 (Alpine)
- **Container Orchestration**: Docker Compose with 4 services
- **Reverse Proxy**: nginx (Alpine) on port 8080
- **Networking**: Custom bridge network with health checks

## Key Features

### BOM Comparison Algorithm
1. **Intelligent Header Detection**: Automatically finds header rows in Excel files (scans first 30 rows)
2. **Column Mapping**: Smart mapping of columns to standard fields:
   - MPN (Manufacturer Part Number) - Primary key for comparison
   - Ref Des/LOC (Reference Designator/Location)  
   - Qty (Quantity)
   - Description
3. **Comparison Categories**:
   - **Delete**: Parts only in File 1 (removed parts)
   - **Add**: Parts only in File 2 (new parts)
   - **Change**: Parts with data differences (qty/description/refdes changes)

### Frontend Features
- **Drag & Drop Upload**: Intuitive file upload for .xlsx and .xls files
- **Real-time Search**: Filter results by MPN or Reference Designator
- **Expandable Categories**: Collapsible sections for each comparison category
- **Export Options**: 
  - Print functionality with optimized print styles
  - Excel export with styled worksheets mirroring UI layout
- **Responsive Design**: Mobile-friendly with grid layouts
- **Visual Diff Highlighting**: Yellow highlighting for changed fields in comparison tables

### Advanced Excel Processing
- **Format Support**: .xlsx and .xls files
- **Unicode Handling**: Safe printing functions for Windows Unicode issues
- **Number Formatting**: Intelligent handling of numeric vs string quantities
- **MPN Preservation**: Maintains original MPN formatting (handles integers as strings)
- **Reference Designator Parsing**: Splits and normalizes ref des lists (comma/semicolon separated)

## Docker Services Configuration

### 1. PostgreSQL Database
- **Image**: postgres:15-alpine
- **Container**: bom_comparison_db
- **Credentials**: postgres/Letmein_123
- **Database**: bom_comparison
- **Health Check**: pg_isready with 10s intervals

### 2. Backend API
- **Build**: Dockerfile.backend (Python 3.11-slim)
- **Container**: bom_comparison_backend
- **Port**: 8000 (internal)
- **Features**: Non-root user, system dependencies for pandas/numpy

### 3. Frontend Application  
- **Build**: Dockerfile.frontend (Node 18-alpine, multi-stage)
- **Container**: bom_comparison_frontend
- **Port**: 3000 (internal)
- **Build**: Next.js standalone output with static files

### 4. Nginx Reverse Proxy
- **Image**: nginx:alpine
- **Container**: bom_comparison_nginx
- **Port**: 8080 (external)
- **Features**: 
  - Rate limiting (10r/s API, 30r/s web)
  - CORS headers
  - Gzip compression
  - Security headers
  - 16MB client max body size for file uploads

## File Structure

### Core Application Files
```
├── api/                     # Python FastAPI backend
│   ├── main.py             # FastAPI application and endpoints
│   ├── excel_tool.py       # Core BOM comparison logic
│   └── requirements.txt    # Python dependencies
├── app/                    # Next.js frontend
│   ├── globals.css         # Global styles and Tailwind
│   ├── layout.tsx          # Root layout component
│   └── page.tsx            # Main comparison interface (851 lines)
├── components/             # React components (if any)
├── src/                    # Python utilities
│   ├── database/           # Database models
│   └── utils/              # Excel helpers
├── nginx/                  # Nginx configuration
├── data/                   # Application data storage
└── logs/                   # Application logs
```

### Configuration Files
- `docker-compose.yml` - Multi-service orchestration
- `Dockerfile.backend` - Python API container
- `Dockerfile.frontend` - Next.js app container  
- `package.json` - Node.js dependencies and scripts
- `tsconfig.json` - TypeScript configuration
- `tailwind.config.js` - Tailwind CSS customization
- `next.config.js` - Next.js build configuration

## Development & Deployment

### Local Development Scripts
- `npm run dev` - Start Next.js development server
- `npm run build` - Build production Next.js app
- `npm run start` - Start production Next.js server
- `npm run lint` - Run ESLint
- `npm run type-check` - TypeScript type checking

### Docker Deployment
- Single command deployment: `docker-compose up -d`
- All services auto-restart unless stopped
- Health checks ensure proper startup sequence
- Nginx serves on port 8080 for external access

### Batch Scripts (Windows)
- `deploy.bat` - Docker compose deployment
- `create-portable.bat` - Portable version creation
- `ngrok-setup.bat` - ngrok tunnel setup
- `network-troubleshoot.bat` - Network diagnostics

## Key Algorithm Details

### MPN (Manufacturer Part Number) Detection Priority
1. **Priority 10**: Exact "MPN" column
2. **Priority 8**: "Manufacturer Part Number" variations
3. **Priority 6**: "Vendor Part Number" variations  
4. **Priority 4**: Generic "Part Number" variations

### Comparison Logic
- **Primary Key**: MPN (normalized to uppercase for comparison)
- **Change Detection**: Compares quantities and descriptions after normalization
- **Reference Designator Handling**: Parses comma/semicolon separated lists
- **Line Number Tracking**: Maintains Excel row references (+2 for header offset)

### Header Detection Algorithm
- Scans first 30 rows of Excel files
- Scores rows based on header-like keywords
- Flexible threshold system (minimum score 4 with 2+ keywords)
- Falls back to best candidate if no perfect match

## Testing & Quality Assurance

### Test Files Directory
Contains various BOM Excel files for testing:
- Different manufacturers (Harsco, Schneider, etc.)
- Various formats (.xls, .xlsx)
- Different column naming conventions
- Edge cases and malformed files

### Error Handling
- **Frontend**: Comprehensive error states with user-friendly messages
- **Backend**: Exception handling with detailed logging
- **File Validation**: Format and size restrictions
- **CORS**: Handles cross-origin requests for development/ngrok

## Security & Production Considerations

### Security Features
- **Non-root Containers**: All services run as non-root users
- **Rate Limiting**: API and web request throttling
- **Security Headers**: X-Frame-Options, X-Content-Type-Options, etc.
- **Input Validation**: File type and size restrictions
- **CORS Configuration**: Controlled cross-origin access

### Production Ready Features
- **Health Checks**: Database and application health monitoring
- **Logging**: Structured logging with log rotation
- **Graceful Shutdowns**: Proper container lifecycle management
- **Static Asset Optimization**: Nginx caching and compression
- **Error Pages**: Custom error handling and user feedback

## Recent Changes & Evolution

### Git History
- **Initial Commit**: BOM Comparison Tool (368f13a)
- **Restructured**: From Flask/simple Python to modern Next.js + FastAPI
- **Deleted Legacy Files**: app.py, config.py, requirements.txt (old structure)
- **Added Modern Stack**: Docker orchestration, TypeScript frontend, FastAPI backend

### Current Status
- **Branch**: master
- **Modified Files**: .gitignore, docker-compose.yml, excel_tool.py
- **New Architecture**: Complete rewrite with modern web technologies
- **Production Ready**: Docker-based deployment with nginx reverse proxy

## Usage Instructions

### For End Users
1. **Start Application**: Run `docker-compose up -d` or use deploy.bat
2. **Access Interface**: Navigate to http://localhost:8080
3. **Upload Files**: Drag and drop two Excel BOM files
4. **Compare**: Click "Compare Files" button
5. **Review Results**: Examine Delete/Add/Change categories
6. **Export**: Use Print or Excel export features

### For Developers
1. **Backend Development**: Modify `api/` files, restart backend container
2. **Frontend Development**: Use `npm run dev` for hot reload
3. **Database Changes**: Update `src/database/models.py`
4. **Deployment**: Modify `docker-compose.yml` and redeploy

## Performance & Scalability

### Current Limitations
- **File Size**: Limited by nginx client_max_body_size (16MB)
- **Processing Time**: Synchronous processing may timeout on very large files
- **Concurrency**: Single-threaded Python processing per request
- **Memory**: In-memory pandas processing limits file size

### Optimization Opportunities
- **Async Processing**: Background job queue for large files
- **Streaming**: Chunk-based Excel processing
- **Caching**: Redis for repeated comparisons
- **Load Balancing**: Multiple backend instances

## Maintenance & Monitoring

### Log Locations
- **Nginx**: `logs/nginx/access.log`, `logs/nginx/error.log`
- **Application**: Container logs via `docker-compose logs`
- **Database**: PostgreSQL logs in container

### Backup Strategy
- **Database**: PostgreSQL data in named volume `postgres_data`
- **Uploaded Files**: Temporary files in `data/` directory
- **Configuration**: All config files in git repository

## Integration Points

### API Integration
- **RESTful API**: JSON responses for all endpoints
- **File Upload**: Multipart form data handling
- **CORS Enabled**: Cross-origin requests supported
- **Error Codes**: HTTP status codes with detailed error messages

### External Tools
- **ngrok**: Tunnel setup for external access
- **GitHub**: Version control and issue tracking
- **Docker Hub**: Container image hosting (potential)

---

*Last Updated: 2025-08-20*
*Project Status: Active Development*
*Architecture: Microservices with Docker Compose*