"""Bounded private page rendering. No files or credentials written to disk."""
import io
import sys
from .extraction import MAX_BYTES,MAX_PAGES,MAX_IMAGE_PIXELS


def render(data,mime,page):
    from PIL import Image,ImageOps
    if not data or len(data)>MAX_BYTES or not 1<=page<=MAX_PAGES:
        raise ValueError('PREVIEW_LIMIT')
    if mime=='application/pdf':
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(data) as doc:
            if not 1<=len(doc)<=MAX_PAGES or page>len(doc):raise ValueError('PAGE_NOT_FOUND')
            p=doc[page-1]
            try:
                width,height=p.get_size()
                if width<=0 or height<=0:raise ValueError('INVALID_PAGE')
                bitmap=p.render(scale=min(2,1600/max(width,height)))
                try:img=bitmap.to_pil().convert('RGB')
                finally:bitmap.close()
            finally:p.close()
    elif mime in ('image/jpeg','image/png') and page==1:
        Image.MAX_IMAGE_PIXELS=MAX_IMAGE_PIXELS
        expected='JPEG' if mime=='image/jpeg' else 'PNG'
        with Image.open(io.BytesIO(data),formats=[expected]) as original:
            if original.width*original.height>MAX_IMAGE_PIXELS:raise ValueError('PREVIEW_LIMIT')
            img=ImageOps.exif_transpose(original).convert('RGB');img.thumbnail((1600,1600))
    else:raise ValueError('PAGE_NOT_FOUND')
    out=io.BytesIO();img.save(out,format='PNG');return out.getvalue()


if __name__=='__main__':
    try:
        sys.stdout.buffer.write(render(sys.stdin.buffer.read(MAX_BYTES+1),sys.argv[1],int(sys.argv[2])))
    except Exception:
        sys.stderr.write('PREVIEW_UNAVAILABLE');raise SystemExit(2)
