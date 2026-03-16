# TB Chest Counter Admin API

This is a standalone Express.js API server for the TB Chest Counter admin panel. It provides endpoints for job management, schedule configuration, and system diagnostics.

## Why This Exists

Azure Static Web Apps' managed functions don't support custom npm packages like `pg` (PostgreSQL client). This standalone API server can be deployed to Azure Container Apps where we have full control over dependencies.

## Architecture

```
Dashboard (Static Web App) --> Admin API (Container App) --> PostgreSQL Database
```

## Endpoints

- `GET /api/admin?action=status` - Get recent job runs and stats
- `GET /api/admin?action=logs` - Get activity logs
- `POST /api/admin?action=trigger` - Record job trigger request
- `GET /api/admin?action=health` - System diagnostics
- `GET/POST /api/admin?action=schedule` - Manage job schedules

All endpoints require `X-Admin-Code: FOR2026-ADMIN` header.

## Deployment

### Prerequisites

1. Azure CLI installed and logged in
2. Docker installed
3. Access to the existing resource group and container registry

### Deploy to Azure Container Apps

```powershell
# From the api-server directory
cd api-server

# Run the deployment script
.\deploy-api.ps1
```

The script will:
1. Build the Docker image
2. Push it to your Azure Container Registry
3. Create/update a Container App with the API
4. Output the API URL

### Update Dashboard

After deployment, update the dashboard to use the new API URL:

1. Create a `.env` file in the dashboard directory:
```
VITE_API_BASE=https://your-api-url.azurecontainerapps.io
```

2. Rebuild and redeploy the dashboard:
```powershell
cd dashboard
npm run build
# Deploy via GitHub Actions or manually
```

## Local Development

```bash
# Install dependencies
npm install

# Set environment variables
export POSTGRES_CONNECTION_STRING="your-connection-string"
export PORT=8080

# Run the server
npm start
```

## Environment Variables

- `POSTGRES_CONNECTION_STRING` - PostgreSQL connection string (required)
- `PORT` - Server port (default: 8080)

## Security

The API uses a simple header-based authentication (`X-Admin-Code`). In production, consider:
- Using Azure AD authentication
- Implementing rate limiting
- Adding request logging
- Using HTTPS only (handled by Container Apps)

## Troubleshooting

### API returns 404
- Check if the Container App is running: `az containerapp show --name tb-chest-admin-api --resource-group rg-tb-chest-counter-dev`
- Verify the ingress is enabled and set to external

### Database connection fails
- Verify the PostgreSQL connection string in Container App environment variables
- Check if the Container App has network access to the database

### CORS issues
- The API has CORS enabled for all origins (`*`)
- If still having issues, check browser console for specific error messages