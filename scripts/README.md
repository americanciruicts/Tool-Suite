# Deployment & Utility Scripts

This directory contains various scripts for deploying and managing the BOM Comparison Tool.

## Deployment Scripts

### `deploy.bat` / `deploy.sh`
Main deployment script that starts the Docker Compose stack.

### `deploy-network.bat` / `deploy-network.sh`
Network-specific deployment scripts with custom networking configurations.

## Development & Tunneling Scripts

### `ngrok-setup.bat` / `setup-ngrok.bat`
Scripts to configure ngrok tunneling for external access during development.

### `start-tunnel.bat`
Starts an ngrok tunnel for the application.

### `quick-share.bat`
Quick sharing script for temporary access.

## Utility Scripts

### `create-portable.bat`
Creates a portable version of the application.

### `network-troubleshoot.bat`
Network diagnostic and troubleshooting utilities.

## Usage

Run scripts from the project root directory:

```bash
# Windows
scripts\deploy.bat

# Linux/Mac
scripts/deploy.sh
```

All scripts assume they are being run from the project root directory.