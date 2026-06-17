from income_ledger.server import parse_multipart_form_file


def _build_multipart_body(boundary: str, field_name: str, filename: str, file_bytes: bytes) -> bytes:
    parts = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
    )
    parts.append(b"Content-Type: application/pdf\r\n\r\n")
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


def test_parse_multipart_extracts_file_field():
    boundary = "TestBoundary123"
    body = _build_multipart_body(boundary, "statement", "test.pdf", b"%PDF-1.4 fake content")
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse_multipart_form_file(body, content_type, "statement")
    assert result is not None
    filename, file_bytes = result
    assert filename == "test.pdf"
    assert file_bytes == b"%PDF-1.4 fake content"


def test_parse_multipart_returns_none_for_missing_field():
    boundary = "TestBoundary123"
    body = _build_multipart_body(boundary, "other_field", "test.pdf", b"content")
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse_multipart_form_file(body, content_type, "statement")
    assert result is None


def test_parse_multipart_returns_none_without_boundary():
    result = parse_multipart_form_file(b"junk", "multipart/form-data", "statement")
    assert result is None


def test_parse_multipart_handles_binary_pdf_content():
    boundary = "TestBoundary123"
    fake_pdf_bytes = b"%PDF-1.4\n\x00\x01\x02binary garbage\xff\xfe\nendobj"
    body = _build_multipart_body(boundary, "statement", "real.pdf", fake_pdf_bytes)
    content_type = f"multipart/form-data; boundary={boundary}"

    result = parse_multipart_form_file(body, content_type, "statement")
    assert result is not None
    filename, file_bytes = result
    assert filename == "real.pdf"
    assert file_bytes == fake_pdf_bytes
