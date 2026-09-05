import os
import ast
import hashlib
from typing import List, Dict, Any

def get_file_hash(filepath: str) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


class BaseParser:
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        """
        Returns a list of evidence chunks:
        [{
           "extracted_content": str,
           "location_json": dict,
           "evidence_type": str
        }]
        """
        raise NotImplementedError


class MarkdownParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        chunks = []
        filename = os.path.basename(filepath)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        current_heading = "Root"
        current_chunk_lines = []
        start_line = 1

        for i, line in enumerate(lines, 1):
            if line.startswith("#"):
                if current_chunk_lines:
                    text = "".join(current_chunk_lines).strip()
                    if text:
                        chunks.append({
                            "extracted_content": text,
                            "location_json": {
                                "file": filename,
                                "section": current_heading,
                                "line_range": [start_line, i - 1]
                            },
                            "evidence_type": "markdown_section"
                        })
                current_heading = line.strip("#").strip()
                current_chunk_lines = [line]
                start_line = i
            else:
                current_chunk_lines.append(line)

        if current_chunk_lines:
            text = "".join(current_chunk_lines).strip()
            if text:
                chunks.append({
                    "extracted_content": text,
                    "location_json": {
                        "file": filename,
                        "section": current_heading,
                        "line_range": [start_line, len(lines)]
                    },
                    "evidence_type": "markdown_section"
                })

        return chunks


class CSVExcelParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        import pandas as pd
        chunks = []
        filename = os.path.basename(filepath)
        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".csv":
            df = pd.read_csv(filepath)
            chunks.append({
                "extracted_content": f"CSV Summary of {filename}:\nColumns: {list(df.columns)}\nRows: {len(df)}\nSample Data:\n{df.head(10).to_string()}",
                "location_json": {"file": filename, "type": "csv_summary", "rows": len(df)},
                "evidence_type": "table_summary"
            })
            for idx, row in df.iterrows():
                row_str = ", ".join([f"{col}: {val}" for col, val in row.items()])
                chunks.append({
                    "extracted_content": f"Row {idx + 1} in {filename}: {row_str}",
                    "location_json": {"file": filename, "row_index": idx + 1},
                    "evidence_type": "data_row"
                })
        elif ext in [".xlsx", ".xls"]:
            xl = pd.ExcelFile(filepath)
            for sheet in xl.sheet_names:
                df = xl.parse(sheet)
                chunks.append({
                    "extracted_content": f"Sheet '{sheet}' in {filename}:\nColumns: {list(df.columns)}\nSample:\n{df.head(10).to_string()}",
                    "location_json": {"file": filename, "sheet": sheet, "rows": len(df)},
                    "evidence_type": "excel_sheet"
                })
        return chunks


class PythonCodeParser(BaseParser):
    """Static AST parser for source code. NEVER executes code."""
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        chunks = []
        filename = os.path.basename(filepath)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            code_text = f.read()

        try:
            tree = ast.parse(code_text, filename=filepath)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = node.name
                    node_type = "class" if isinstance(node, ast.ClassDef) else "function"
                    lineno = getattr(node, "lineno", 1)
                    end_lineno = getattr(node, "end_lineno", lineno)
                    docstring = ast.get_docstring(node) or ""
                    chunks.append({
                        "extracted_content": f"Code Structure ({node_type} {name}):\nDocstring: {docstring}\nLines: {lineno}-{end_lineno}",
                        "location_json": {
                            "file": filename,
                            "symbol": name,
                            "symbol_type": node_type,
                            "line_range": [lineno, end_lineno]
                        },
                        "evidence_type": "code_ast"
                    })
        except Exception:
            # Fallback text parsing if AST fails
            lines = code_text.splitlines()
            chunks.append({
                "extracted_content": f"Source Code File {filename} ({len(lines)} lines)",
                "location_json": {"file": filename, "line_range": [1, len(lines)]},
                "evidence_type": "code_raw"
            })
        return chunks


class PDFParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        import fitz  # PyMuPDF
        chunks = []
        filename = os.path.basename(filepath)
        doc = fitz.open(filepath)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                chunks.append({
                    "extracted_content": f"PDF Page {page_num + 1} of {filename}:\n{text.strip()}",
                    "location_json": {"file": filename, "page": page_num + 1},
                    "evidence_type": "pdf_page"
                })
        doc.close()
        return chunks


class PlainTextParser(BaseParser):
    def parse(self, filepath: str) -> List[Dict[str, Any]]:
        chunks = []
        filename = os.path.basename(filepath)
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
        if text:
            chunks.append({
                "extracted_content": f"File {filename}:\n{text}",
                "location_json": {"file": filename},
                "evidence_type": "text_document"
            })
        return chunks


def get_parser(filepath: str) -> BaseParser:
    ext = os.path.splitext(filepath)[1].lower()
    if ext in [".md", ".markdown"]:
        return MarkdownParser()
    elif ext in [".csv", ".xlsx", ".xls"]:
        return CSVExcelParser()
    elif ext == ".py":
        return PythonCodeParser()
    elif ext == ".pdf":
        return PDFParser()
    else:
        return PlainTextParser()
