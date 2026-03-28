"""Azure Blob Storage utilities for debug screenshots."""

import logging
import os
from datetime import datetime

log = logging.getLogger(__name__)


def upload_screenshot(local_path: str, blob_name: str = None) -> str:
    """Upload a screenshot to Azure Blob Storage.

    Args:
        local_path: Path to the local file
        blob_name: Optional blob name (defaults to timestamped name)

    Returns:
        The blob URL, or empty string on failure
    """
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        log.warning("azure-storage-blob not installed, skipping upload")
        return ""

    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        log.warning("AZURE_STORAGE_CONNECTION_STRING not set, skipping upload")
        return ""

    container_name = "scanner-screenshots"

    if not blob_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        blob_name = f"debug/{timestamp}.png"

    try:
        blob_service = BlobServiceClient.from_connection_string(conn_str)
        blob_client = blob_service.get_blob_client(container=container_name, blob=blob_name)

        with open(local_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=True)

        url = blob_client.url
        log.info(f"Uploaded screenshot to: {url}")
        return url

    except Exception as e:
        log.warning(f"Failed to upload screenshot: {e}")
        return ""
