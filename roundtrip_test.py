import argparse
import os

from docx import Document


def roundtrip(input_path: str, output_path: str) -> str:
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input DOCX not found: {input_path}")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or os.getcwd(), exist_ok=True)
    doc = Document(input_path)
    doc.save(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-trip DOCX via python-docx (open+save)")
    parser.add_argument("input", help="Path to input .docx file")
    parser.add_argument("--out", help="Output path (default: output/<name>_roundtrip.docx)")
    args = parser.parse_args()

    inp = args.input
    if args.out:
        out = args.out
    else:
        base = os.path.splitext(os.path.basename(inp))[0]
        out_dir = "output"
        out = os.path.join(out_dir, f"{base}_roundtrip.docx")

    result = roundtrip(inp, out)
    print(result)


if __name__ == "__main__":
    main()
