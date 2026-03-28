# WSL Fix for TB Chest Counter - Linux Image Build

## Current Status
- **Problem**: The scanner fails to authenticate in cloud (gets stuck at login screen)
- **Solution**: Pre-bake session cookies into Docker image
- **Issue**: Current image was built on Windows (not compatible with Azure Container Apps which needs Linux/amd64)
- **Fix**: Build the image in WSL to create Linux-compatible container

## What's Already Done
1. ✅ **Modified Dockerfiles** - Added `COPY data/browser_data/` to both Dockerfile and Dockerfile.scanner
2. ✅ **Updated .dockerignore** - Commented out browser_data exclusion (line 18)
3. ✅ **Session cookies exist** - data/browser_data contains cookies from March 18 local session
4. ✅ **Requirements updated** - azure-storage-blob added for screenshot uploads
5. ❌ **Windows image built** - But not compatible with Azure Container Apps

## Steps to Execute in WSL

### 1. Navigate to Project Directory
```bash
cd /mnt/c/sourcenew/repos/spanko/tb-chest-counter
```

### 2. Build Linux Image with Cookies
```bash
# Build the image with pre-baked cookies
docker build -t tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:cookies-linux -f Dockerfile .

# This will:
# - Use the Playwright Python base image
# - Install all requirements
# - Copy src, config, calibration.json
# - Copy data/browser_data with session cookies (439MB)
# - Create a Linux/amd64 compatible image
```

### 3. Login to Azure Container Registry
```bash
az acr login --name tbdevacrb7jbhj
```

### 4. Push the Image
```bash
# Push the cookies-linux image
docker push tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:cookies-linux

# Tag as latest
docker tag tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:cookies-linux tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:latest

# Push latest
docker push tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:latest
```

### 5. Update Container App to Use New Image
```bash
az containerapp job update \
  --name tbdev-scan-for-main \
  --resource-group rg-tb-chest-counter-dev \
  --image tbdevacrb7jbhj.azurecr.io/tb-chest-scanner:latest
```

### 6. Trigger and Test the Scanner
```bash
# Start the job
az containerapp job start \
  --name tbdev-scan-for-main \
  --resource-group rg-tb-chest-counter-dev

# Check execution status
az containerapp job execution list \
  --name tbdev-scan-for-main \
  --resource-group rg-tb-chest-counter-dev \
  --output table
```

### 7. Monitor Logs
```bash
# Check container logs (might take a minute to appear)
az monitor log-analytics query \
  --workspace 84afec13-9a92-4daf-af9f-620e7cd84767 \
  --analytics-query "ContainerAppConsoleLogs_CL | where TimeGenerated > ago(10m) | where ContainerAppName_s == 'tbdev-scan-for-main' | order by TimeGenerated desc | project TimeGenerated, Log_s" \
  --output tsv
```

### 8. Verify Success in PostgreSQL
```bash
# Check if chests were extracted (password: 7k!vBq#9sT2@xL4mH)
docker run --rm -it postgres:16 psql \
  "host=tbdev-pg-b7jbhj.postgres.database.azure.com port=5432 dbname=tbchests user=tbadmin sslmode=require" \
  -c "SELECT * FROM scan_runs WHERE clan_id='for-main' ORDER BY started_at DESC LIMIT 5;"
```

## Expected Outcome
With the Linux image containing pre-baked cookies:
1. Scanner should bypass the login screen (cookies authenticate automatically)
2. Navigate to Gifts tab successfully
3. Extract chest data using Claude Vision
4. Store results in PostgreSQL
5. Job status should be "Succeeded" not "Failed"

## Alternative if Cookies Don't Work
If the cookies have expired or don't work:
1. Deploy the image anyway (it has all the code fixes)
2. Manually trigger a job with visible browser to generate fresh cookies
3. Extract the new browser_data and rebuild the image

## Key Files Modified
- `.dockerignore` - Line 18: commented out browser_data exclusion
- `Dockerfile` - Line 34: added COPY data/browser_data/
- `Dockerfile.scanner` - Line 34: added COPY data/browser_data/
- `requirements.txt` - Line 17: added azure-storage-blob>=12.19.0

## Important Notes
- The browser_data folder is 439MB (contains Chromium profile with cookies)
- Cookies are from March 18, 2024 - should still be valid
- Must build on Linux/WSL for Azure Container Apps compatibility
- Current "latest" image in ACR doesn't have cookies (that's why login fails)