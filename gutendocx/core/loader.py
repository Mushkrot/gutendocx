import os
import shutil
import tempfile
import zipfile

from docx import Document


class Loader:
    def open(self, input_path):
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"Input DOCX not found: {input_path}")
        return Document(input_path)

    def save(self, document, output_path):
        if document is None:
            raise ValueError("document must not be None")
        out_dir = os.path.dirname(os.path.abspath(output_path)) or os.getcwd()
        os.makedirs(out_dir, exist_ok=True)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp_path = tmp.name

        try:
            document.save(tmp_path)
            self._validate_docx(tmp_path)
            shutil.move(tmp_path, output_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return output_path

    def _validate_docx(self, path):
        if not zipfile.is_zipfile(path):
            raise ValueError("Output is not a valid DOCX (zip) file")
        with zipfile.ZipFile(path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                raise ValueError("DOCX missing core part: word/document.xml")
