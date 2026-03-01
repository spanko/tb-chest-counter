"""
OCR Engine — Image preprocessing + text extraction.

Supports two backends:
1. Tesseract OCR (free, local, good enough for most cases)
2. Azure AI Vision (paid, cloud, dramatically better accuracy on game fonts)

The image preprocessing pipeline follows the pattern from SICGames/TBChestTracker:
    Grayscale → Resize (upscale) → Threshold (binarize) → Invert

This cleans up the game's rendered text for better OCR results.
"""

import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("tb-chest-counter.ocr")


class OCREngine:
    """Unified OCR interface supporting Tesseract and Azure AI Vision."""

    def __init__(self, config: dict):
        self.engine = config.get("ocr_engine", "tesseract")
        self.config = config

        if self.engine == "tesseract":
            self._init_tesseract(config)
        elif self.engine == "azure":
            self._init_azure(config)
        else:
            raise ValueError(f"Unknown OCR engine: {self.engine}")

    # ── Tesseract Setup ────────────────────────────────────────

    def _init_tesseract(self, config: dict):
        import pytesseract

        # Allow custom tesseract path (Windows often needs this)
        custom_path = config.get("tesseract_path")
        if custom_path:
            pytesseract.pytesseract.tesseract_cmd = custom_path

        self._pytesseract = pytesseract
        log.info("OCR engine: Tesseract (local)")

    # ── Azure AI Vision Setup ──────────────────────────────────

    def _init_azure(self, config: dict):
        endpoint = config.get("azure_vision_endpoint")
        key = config.get("azure_vision_key")

        if not endpoint or not key:
            raise ValueError(
                "Azure AI Vision requires 'azure_vision_endpoint' and 'azure_vision_key' in config"
            )

        self._azure_endpoint = endpoint.rstrip("/")
        self._azure_key = key
        log.info(f"OCR engine: Azure AI Vision ({self._azure_endpoint})")

    # ── Public Interface ───────────────────────────────────────

    def extract_text(self, image: Image.Image) -> str:
        """
        Preprocess the image and extract text via the configured OCR engine.

        Args:
            image: PIL Image of the gift region screenshot

        Returns:
            Extracted text string
        """
        # Preprocess
        processed = self._preprocess(image)

        # Run OCR
        if self.engine == "tesseract":
            return self._ocr_tesseract(processed)
        elif self.engine == "azure":
            return self._ocr_azure(processed)

    # ── Image Preprocessing Pipeline ───────────────────────────

    def _preprocess(self, image: Image.Image) -> Image.Image:
        """
        Clean up the screenshot for better OCR accuracy.

        Pipeline: Grayscale → Upscale 2x → Gaussian Blur → Threshold → Invert

        This follows the proven pattern from TBChestTracker (SICGames).
        """
        # Convert PIL → OpenCV (numpy array)
        img = np.array(image)

        # 1. Grayscale
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img

        # 2. Upscale 2x (helps Tesseract with small text)
        h, w = gray.shape
        upscaled = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # 3. Light Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(upscaled, (3, 3), 0)

        # 4. Adaptive threshold (binarize)
        # Using adaptive threshold handles varying brightness across the game UI
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8
        )

        # 5. Invert (Tesseract prefers dark text on white background)
        inverted = cv2.bitwise_not(thresh)

        # Convert back to PIL
        return Image.fromarray(inverted)

    # ── Tesseract OCR ──────────────────────────────────────────

    def _ocr_tesseract(self, image: Image.Image) -> str:
        """Run Tesseract OCR on a preprocessed image."""
        try:
            # Tesseract config:
            # --psm 6 = Assume a single uniform block of text
            # --psm 4 = Assume a single column of text
            # -c tessedit_char_whitelist = Restrict to expected characters
            text = self._pytesseract.image_to_string(
                image,
                lang="eng",
                config="--psm 6",
            )
            return text.strip()
        except Exception as e:
            log.error(f"Tesseract OCR failed: {e}")
            return ""

    # ── Azure AI Vision OCR ────────────────────────────────────

    def _ocr_azure(self, image: Image.Image) -> str:
        """Run Azure AI Vision Read API on a preprocessed image."""
        import requests
        import time

        try:
            # Convert PIL image to PNG bytes
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()

            # Submit read request
            read_url = f"{self._azure_endpoint}/vision/v3.2/read/analyze"
            headers = {
                "Ocp-Apim-Subscription-Key": self._azure_key,
                "Content-Type": "application/octet-stream",
            }
            response = requests.post(read_url, headers=headers, data=image_bytes)
            response.raise_for_status()

            # Get the operation URL from the response header
            operation_url = response.headers["Operation-Location"]

            # Poll for results (Azure Read API is async)
            while True:
                result = requests.get(
                    operation_url,
                    headers={"Ocp-Apim-Subscription-Key": self._azure_key},
                )
                result_json = result.json()
                status = result_json.get("status")

                if status == "succeeded":
                    break
                elif status == "failed":
                    log.error("Azure OCR analysis failed")
                    return ""
                else:
                    time.sleep(0.5)

            # Extract text from results
            lines = []
            for read_result in result_json.get("analyzeResult", {}).get("readResults", []):
                for line in read_result.get("lines", []):
                    lines.append(line.get("text", ""))

            return "\n".join(lines)

        except Exception as e:
            log.error(f"Azure OCR failed: {e}")
            return ""
