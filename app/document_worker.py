"""CPU/parser isolation. stdin is file bytes; stdout is bounded extracted text JSON."""
import sys
from .extraction import MAX_BYTES, ExtractionError, read_document

if __name__ == '__main__':
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        document = read_document(data, sys.argv[1])
        sys.stdout.write(document.model_dump_json())
    except ExtractionError as e:
        sys.stdout.write('{"error_code":"' + e.code + '"}')
        sys.exit(2)
    except Exception:
        sys.stdout.write('{"error_code":"DOCUMENT_READ_FAILED"}')
        sys.exit(2)
