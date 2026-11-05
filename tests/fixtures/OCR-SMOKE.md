# Local OCR fixture smoke test

- PASS: clean payable-value crop yields INR 10,000.00.
- PASS: deliberately blurred payable-value crop yields no numeric text.

This only tests the cropped visual source using local Tesseract, not Gemini, field evidence gates, invoice matching or application decisions. Other visible invoice values can still suggest a calculated total; the backend must not treat that inference as a supported printed payable amount.
