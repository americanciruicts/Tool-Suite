# BOM Comparison Tool - Internal Hosting Guide

## Quick Start for Internal Network Access

**Windows:**
```cmd
deploy-network.bat
```

**Linux/Mac:**
```bash
./deploy-network.sh
```

**For local-only access:**
```cmd
deploy.bat    (Windows)
./deploy.sh   (Linux/Mac)
```

## Network Access

After running the network deployment script, the tool will be available at:
- **Local access:** http://localhost
- **Network access:** http://YOUR-SERVER-IP

**Share this URL with employees:** The script will display the exact URL to share.

### Firewall Configuration

Ensure port 80 is open on your server:

**Windows:**
- Windows Defender Firewall → Allow an app → Add port 80
- Or run: `netsh advfirewall firewall add rule name="BOM Tool" dir=in action=allow protocol=TCP localport=80`

**Linux:**
- Ubuntu/Debian: `sudo ufw allow 80`
- CentOS/RHEL: `sudo firewall-cmd --permanent --add-port=80/tcp && sudo firewall-cmd --reload`

## Prerequisites

- Docker Desktop installed and running
- At least 4GB RAM available
- Port 80 available on the host machine

## Architecture

The application consists of 4 services:

- **Frontend**: Next.js web application (port 3000 internal)
- **Backend**: Python FastAPI server (port 8000 internal)
- **Database**: PostgreSQL 15 (port 5432 internal)
- **Nginx**: Reverse proxy and load balancer (port 80 exposed)

## Manual Deployment

1. **Build and start services:**
   ```bash
   docker-compose build
   docker-compose up -d
   ```

2. **Check status:**
   ```bash
   docker-compose ps
   docker-compose logs -f
   ```

3. **Stop services:**
   ```bash
   docker-compose down
   ```

## Configuration

- **Environment**: Edit `.env.production` for production settings
- **Database**: PostgreSQL data persists in `postgres_data` volume
- **Uploads**: File uploads are stored in `./data` volume
- **Logs**: Nginx logs available in `./logs/nginx/`

## Employee Access Instructions

Once deployed, share these instructions with your employees:

1. **Access the tool:** Open your web browser and go to `http://YOUR-SERVER-IP`
2. **Upload Excel files:** Use the drag-and-drop interface or click to select files
3. **Compare BOMs:** The tool will automatically process and compare the files
4. **View results:** Download the comparison report or view differences on screen

### Supported File Formats
- .xlsx (Excel 2007+)
- .xls (Excel 97-2003)
- Maximum file size: 16MB per file

## Network Configuration (Advanced)

The deployment scripts automatically configure the application for network access. If you need custom configuration:

1. **Custom domain/hostname:**
   ```bash
   # Edit nginx/nginx.conf
   server_name your-custom-domain.com;
   ```

2. **Restart services:**
   ```bash
   docker-compose restart
   ```

## Security Notes

- Default database password should be changed in production
- Consider adding HTTPS/SSL termination at nginx level
- Rate limiting is configured in nginx.conf
- File upload size limited to 16MB (configurable in nginx)

## Troubleshooting

**Services won't start:**
- Check Docker is running: `docker info`
- Check port 80 is available: `netstat -an | grep :80`

**Database connection issues:**
- Verify postgres container is healthy: `docker-compose ps`
- Check database logs: `docker-compose logs postgres`

**File upload issues:**
- Ensure `./data` directory has write permissions
- Check nginx file size limits in `nginx.conf`

## Monitoring

View real-time logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f frontend
docker-compose logs -f backend
docker-compose logs -f postgres
docker-compose logs -f nginx
```

Check resource usage:
```bash
docker stats
```

## Backup

Database backup:
```bash
docker-compose exec postgres pg_dump -U postgres bom_comparison > backup.sql
```

Restore database:
```bash
cat backup.sql | docker-compose exec -T postgres psql -U postgres bom_comparison
```