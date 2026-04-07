# 🤖 AI BOM Comparison Tool

Modern BOM (Bill of Materials) comparison tool with intelligent Excel file analysis, automated column detection, and visual diff highlighting. Built with Next.js, FastAPI, and Docker for production-ready deployment.

![Next.js](https://img.shields.io/badge/Next.js-14-black.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green.svg)
![TypeScript](https://img.shields.io/badge/TypeScript-5.3-blue.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-orange.svg)
![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## ✨ Features

- **🧠 AI-Powered Column Detection**: Automatically finds and maps MPN, Quantity, Ref Des, and Description columns across different naming conventions
- **🎯 Smart Comparison Categories**:
  - 🔴 **Delete**: Parts only in File 1 (removed)
  - 🟢 **Add**: Parts only in File 2 (new)
  - 🟡 **Change**: Parts with data differences (highlighted)
- **💡 Advanced Features**:
  - Real-time search and filtering
  - Visual diff highlighting for changed fields
  - Print-optimized layouts
  - Excel export with styled worksheets
  - Drag & drop file upload
- **🏗️ Production Ready**:
  - Docker Compose orchestration
  - Nginx reverse proxy with rate limiting
  - PostgreSQL database
  - Health checks and auto-restart

## 🚀 Quick Start

### Prerequisites

- **Docker Desktop** (required)
- **Git**
- **16MB+ free RAM** for containers

### 1-Click Deployment

1. **Clone and start**
   ```bash
   git clone https://github.com/Nav228/AI-BOM-Tool.git
   cd AI-BOM-Tool
   docker-compose up -d
   ```

2. **Access the tool**
   ```
   🌐 http://localhost:8080
   ```

### Alternative: Use Scripts
```bash
# Windows
scripts\deploy.bat

# Linux/Mac  
scripts/deploy.sh
```

## 📁 Modern Architecture

```
AI-BOM-Tool/
├── 🖥️ app/                         # Next.js 14 Frontend
│   ├── page.tsx                    # Main React interface (850+ lines)
│   ├── layout.tsx                  # App layout
│   └── globals.css                 # Tailwind CSS styles
├── 🐍 api/                         # FastAPI Backend
│   ├── main.py                     # API endpoints
│   ├── excel_tool.py               # Core BOM comparison logic
│   └── requirements.txt            # Python dependencies
├── 🔧 scripts/                     # Deployment & utilities
│   ├── deploy.bat/.sh              # Main deployment
│   ├── ngrok-setup.bat             # External access
│   └── README.md                   # Script documentation
├── 📂 assets/                      # Images & screenshots
├── 📋 test_files/                  # Sample BOM Excel files
├── 🌐 nginx/                       # Reverse proxy config
└── 🐳 docker-compose.yml           # Multi-service orchestration
```

## 🛠️ Development

### Local Development
```bash
# Frontend development (with hot reload)
npm run dev

# Backend development
cd api && uvicorn main:app --reload

# Type checking
npm run type-check

# Build production
npm run build
```

## ✅ Final Mile (Security Standards Protocol)

Before any release, complete the Final Mile checks based on `SECURITY_STANDARDS_PROTOCOL.md` (alias: `security_standards.protocol.md`).

Quick start:

```bash
# Windows
scripts\final-mile.bat

# Linux/Mac
bash scripts/final-mile.sh
```

What runs:
- Lint and type-check (frontend)
- Dependency vulnerability audit (Node)
- Optional: Secrets scan (gitleaks) if installed
- Optional: Python SAST (bandit) and dependency audit (safety) if installed
- Optional: k6 performance test (ensure stack is running locally)

See `FINAL_MILE_CHECKLIST.md` for pass/fail criteria and manual verification steps.

### Docker Services
- **Frontend**: Next.js on port 3000 (internal)
- **Backend**: FastAPI on port 8000 (internal) 
- **Database**: PostgreSQL on port 5432 (internal)
- **Nginx**: Reverse proxy on port 8080 (external)

## 📊 Intelligent Processing

### Supported Formats
- **Excel Files**: `.xlsx`, `.xls` (up to 16MB each)
- **Auto-Detection**: Scans first 30 rows for headers
- **Smart Mapping**: Handles 50+ column naming variations

### Column Detection Examples
```
✅ MPN: "MPN", "Part Number", "Manufacturer Part Number", "P/N"
✅ Qty: "Qty", "Quantity", "Count", "Amount"  
✅ RefDes: "RefDes", "Reference Designator", "Location", "Ref Des/LOC"
✅ Description: "Description", "Desc", "Component", "Notes"
```

## 🌐 External Access

For sharing with team members or remote access:

```bash
# Set up ngrok tunnel
scripts\ngrok-setup.bat
scripts\start-tunnel.bat

# Get shareable URL like: https://abc123.ngrok.io
```

## 🔧 Configuration

### Environment Variables
```bash
# Production settings
POSTGRES_DB=bom_comparison
POSTGRES_USER=postgres
NEXT_PUBLIC_API_URL=/api
```

### Nginx Features
- Rate limiting (10 req/s API, 30 req/s web)
- CORS headers for development
- Gzip compression
- Security headers
- 16MB upload limit

## 📈 Performance

- **Processing Speed**: ~1000 parts/second
- **Memory Usage**: ~100MB per service
- **File Limits**: 16MB per Excel file
- **Concurrent Users**: 50+ (rate limited)

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Make changes with proper TypeScript types
4. Test with `npm run type-check`
5. Commit and push (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## 🐛 Troubleshooting

### Common Issues
```bash
# Docker issues
docker-compose down && docker-compose up -d

# Port conflicts
netstat -ano | findstr :8080

# Reset everything
docker-compose down -v && docker system prune -a
```

### Debug Tools
- **Health Check**: http://localhost:8080/health
- **API Docs**: http://localhost:8080/api (FastAPI auto-docs)
- **Logs**: `docker-compose logs [service-name]`

## Owner

**American Circuits Inc.**

Deployed and maintained by **Preet Raval**

## 📝 License

Proprietary — American Circuits Inc. Internal use only.

## 🎯 Roadmap

- [x] ✅ Modern Next.js + FastAPI architecture
- [x] ✅ Docker Compose deployment
- [x] ✅ Intelligent column detection
- [x] ✅ Visual diff highlighting
- [x] ✅ Excel export functionality
- [ ] 🔄 Batch file processing
- [ ] 🔄 User authentication
- [ ] 🔄 Advanced filtering & sorting
- [ ] 🔄 API rate limiting per user
- [ ] 🔄 Cloud deployment templates

---

**🤖 Built with AI assistance • Made with ❤️ for modern BOM analysis** 