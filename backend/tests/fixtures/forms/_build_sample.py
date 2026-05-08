# regenerate fixture: python backend/tests/fixtures/forms/_build_sample.py
"""Build sample_form.hwpx — a minimal HWPX with two paragraphs and one 2×3 table."""

import io
import zipfile
from pathlib import Path

OUT = Path(__file__).parent / "sample_form.hwpx"

MIMETYPE = b"application/hwp+zip"

CONTAINER_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="Contents/content.hpf" media-type="application/hwp+zip"/>
  </rootfiles>
</container>
"""

CONTENT_HPF = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<hpf:HWPFDocumentInformation
    xmlns:hpf="http://www.hancom.co.kr/hwpml/2011/hp">
  <hpf:manifest>
    <hpf:item id="Contents/section0.xml" mediaType="application/xml"/>
  </hpf:manifest>
</hpf:HWPFDocumentInformation>
"""

# Section body: two paragraphs + one 2-row × 3-column table
# Namespaces:
#   hs = http://www.hancom.co.kr/hwpml/2011/section
#   hp = http://www.hancom.co.kr/hwpml/2011/paragraph
SECTION0_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p>
    <hp:run><hp:t>연구의 필요성</hp:t></hp:run>
  </hp:p>
  <hp:p>
    <hp:run><hp:t>예상 결과</hp:t></hp:run>
  </hp:p>
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>연도</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>내용</hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t>비고</hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t></hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t></hp:t></hp:run></hp:p></hp:subList></hp:tc>
      <hp:tc><hp:subList><hp:p><hp:run><hp:t></hp:t></hp:run></hp:p></hp:subList></hp:tc>
    </hp:tr>
  </hp:tbl>
</hs:sec>
""".encode()


def build() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # mimetype must be first and stored uncompressed
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, MIMETYPE)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("Contents/content.hpf", CONTENT_HPF)
        z.writestr("Contents/section0.xml", SECTION0_XML)
    OUT.write_bytes(buf.getvalue())
    print(f"Written {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
