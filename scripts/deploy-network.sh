#!/bin/bash

# BOM Comparison Tool Network Deployment Script
set -e

echo "🚀 Starting BOM Comparison Tool for Internal Network Access..."

# Get the server's IP address
echo "📡 Detecting server IP address..."
if command -v ip &> /dev/null; then
    SERVER_IP=$(ip route get 8.8.8.8 | awk '{print $7; exit}')
elif command -v ifconfig &> /dev/null; then
    SERVER_IP=$(ifconfig | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1' | head -n1)
else
    echo "❌ Could not detect IP address. Please run 'ip addr' or 'ifconfig' manually to find your IP."
    exit 1
fi

if [ -z "$SERVER_IP" ]; then
    echo "❌ Could not detect IP address. Please run 'ip addr' or 'ifconfig' manually to find your IP."
    exit 1
fi

echo "🌐 Server IP detected: $SERVER_IP"
echo

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Stop existing containers if running
echo "🛑 Stopping existing containers..."
docker-compose down || true

# Build containers
echo "🔨 Building containers..."
docker-compose build --no-cache

# Start services
echo "🚀 Starting services..."
docker-compose up -d

# Wait for services to start
echo "⏳ Waiting for services to start..."
sleep 30

# Check service status
echo "🔍 Checking service status..."
docker-compose ps

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "📊 BOM Comparison Tool is now available on the internal network:"
echo "   ✅ Local access:    http://localhost"
echo "   ✅ Network access:  http://$SERVER_IP"
echo ""
echo "📧 Share this URL with employees: http://$SERVER_IP"
echo ""
echo "🔧 Management commands:"
echo "  View logs:     docker-compose logs -f"
echo "  Stop services: docker-compose down"
echo "  Restart:       docker-compose restart"
echo ""
echo "📁 Data is persisted in Docker volumes"
echo "📝 Logs are available in ./logs/nginx/"
echo ""
echo "⚠️  FIREWALL NOTE: Make sure port 80 is open on this server"
echo "   Ubuntu/Debian: sudo ufw allow 80"
echo "   CentOS/RHEL:   sudo firewall-cmd --permanent --add-port=80/tcp && sudo firewall-cmd --reload"