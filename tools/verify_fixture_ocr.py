#!/usr/bin/env python3
"""Small local OCR fixture check, not an application extraction/approval test.
Requires Tesseract on PATH (or --tesseract) and the fixture requirements.
"""
import argparse
import io
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from generate_fixtures import ROOT, W, H, TOTAL_Y, raster


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tesseract',default=shutil.which('tesseract'))
    parser.add_argument('--work-dir',type=Path,default=Path('work/fixture-ocr'))
    args=parser.parse_args()
    if not args.tesseract:
        raise SystemExit('Tesseract not installed: supply --tesseract or install the system binary.')
    args.work_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='smoke-',dir=args.work_dir) as folder:
        directory=Path(folder)
        results={}
        for name in ['scan_clean','scan_blurred_total']:
            image=raster((ROOT/'tests'/'fixtures'/'pdfs'/f'{name}.pdf').read_bytes())
            crop=image.crop((int(334*2),int((H-(TOTAL_Y+10))*2),int((W-49)*2),int((H-(TOTAL_Y-14))*2)))
            target=directory/f'{name}.png'
            crop.save(target)
            done=subprocess.run([args.tesseract,str(target),'stdout','--psm','7','-l','eng'],
                                capture_output=True,text=True,check=True,timeout=30)
            results[name]=done.stdout.strip()
        numeric=re.sub(r'[^0-9.]','',results['scan_clean'])
        assert '10000.00' in numeric, f'Clean crop not read correctly: {results["scan_clean"]!r}'
        blurred_digits=re.sub(r'[^0-9]','',results['scan_blurred_total'])
        assert not blurred_digits, f'Blurred crop still yielded numeric text: {results["scan_blurred_total"]!r}'
    report=('# Local OCR fixture smoke test\n\n'
        '- PASS: clean payable-value crop yields INR 10,000.00.\n'
        '- PASS: deliberately blurred payable-value crop yields no numeric text.\n\n'
        'This only tests the cropped visual source using local Tesseract, not Gemini, field evidence gates, invoice matching or application decisions. Other visible invoice values can still suggest a calculated total; the backend must not treat that inference as a supported printed payable amount.\n')
    (ROOT/'tests'/'fixtures'/'OCR-SMOKE.md').write_text(report)
    print(report)


if __name__=='__main__':
    main()
