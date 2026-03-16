# Custom Domain Setup for TB Chest Dashboard

## Current Azure Static Web App URL
The default URL is: `https://tbdash-for-dev.azurestaticapps.net`

This URL is stable and won't change unless you delete and recreate the Static Web App.

## Setting Up a Custom Domain (CNAME)

### Option 1: Using the Setup Script

Run the PowerShell script:
```powershell
.\setup-custom-domain.ps1 -CustomDomain "tb.yourdomain.com"
```

### Option 2: Manual Setup

#### Step 1: Add CNAME Record in Your DNS Provider

Add a CNAME record pointing to the Static Web App:

| Type | Name | Value |
|------|------|-------|
| CNAME | tb (or your subdomain) | tbdash-for-dev.azurestaticapps.net |

**Examples for popular DNS providers:**

**Cloudflare:**
1. Go to DNS settings
2. Add record:
   - Type: CNAME
   - Name: tb (or @)
   - Target: tbdash-for-dev.azurestaticapps.net
   - Proxy status: DNS only (gray cloud)

**GoDaddy:**
1. Go to DNS Management
2. Add CNAME:
   - Host: tb
   - Points to: tbdash-for-dev.azurestaticapps.net

**Namecheap:**
1. Go to Advanced DNS
2. Add new record:
   - Type: CNAME
   - Host: tb
   - Value: tbdash-for-dev.azurestaticapps.net

#### Step 2: Add Custom Domain in Azure

**Via Azure CLI:**
```bash
az staticwebapp hostname add \
  --hostname "tb.yourdomain.com" \
  --name "tbdash-for-dev" \
  --resource-group "rg-tb-chest-counter-dev"
```

**Via Azure Portal:**
1. Navigate to your Static Web App in Azure Portal
2. Click "Custom domains" in the left menu
3. Click "+ Add"
4. Enter your domain (e.g., tb.yourdomain.com)
5. Follow the validation steps

#### Step 3: Wait for SSL Certificate

Azure automatically provisions an SSL certificate for your custom domain. This usually takes 5-10 minutes.

## Verifying Your Setup

Check if the custom domain is working:
```bash
# List all configured domains
az staticwebapp hostname list \
  --name "tbdash-for-dev" \
  --resource-group "rg-tb-chest-counter-dev" \
  --output table
```

## Using Apex Domain (yourdomain.com)

If you want to use your root domain (e.g., yourdomain.com instead of tb.yourdomain.com):

1. Your DNS provider must support ALIAS/ANAME records (not all do)
2. If not supported, use a subdomain like www or app
3. Cloudflare users can use CNAME flattening for apex domains

## Troubleshooting

### DNS Not Resolving
- Wait 10-15 minutes for DNS propagation
- Check with: `nslookup tb.yourdomain.com`
- Verify CNAME is correct: `dig tb.yourdomain.com CNAME`

### Certificate Error
- Azure needs time to provision SSL (5-10 minutes)
- Ensure domain validation completed in Azure Portal
- Check domain status in Custom domains section

### Domain Already in Use Error
- The domain might be used by another Azure resource
- Remove it from the other resource first
- Or use a different subdomain

## Benefits of Custom Domain

1. **Stable URL**: Your custom domain won't change
2. **Branding**: Use your own domain for professional appearance
3. **SSL Included**: Azure provides free SSL certificate
4. **Global CDN**: Same performance benefits as default URL

## Current Setup Summary

- **Default URL**: https://tbdash-for-dev.azurestaticapps.net
- **Access Code**: FOR2026
- **Admin Code**: FOR2026-ADMIN
- **Custom Domain**: Configure as needed

Once configured, your dashboard will be accessible at both:
- Your custom domain: https://tb.yourdomain.com
- Default Azure URL: https://tbdash-for-dev.azurestaticapps.net