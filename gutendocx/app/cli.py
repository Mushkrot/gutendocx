import argparse
import json
import os
import sys

from ..core.scan import prescan as scan_prescan
from ..core.config import load_config
from ..core.cover import run_cover_pipeline
from ..core.toc import build_toc
from ..core.libreoffice_toc import run_libreoffice_convert


def cmd_prescan(args):
    try:
        inv = scan_prescan(args.input)
        if args.out:
            out_dir = os.path.dirname(os.path.abspath(args.out))
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(inv, f, ensure_ascii=False, indent=2)
        summary = inv.get("summary", {})
        p_styles = inv.get("paragraph", {})
        c_styles = inv.get("character", {})
        t_styles = inv.get("table", {})
        print(
            f"paragraphs={summary.get('paragraph_total', 0)} runs={summary.get('run_total', 0)} tables={summary.get('table_total', 0)}"
        )
        print(
            f"styles: paragraph={len(p_styles)} character={len(c_styles)} table={len(t_styles)}"
        )
        if args.out:
            print(f"report written: {args.out}")
    except Exception as e:
        print(f"prescan failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_apply_styles(args):
    print("apply-styles: not implemented yet")


def cmd_layout(args):
    print("layout: not implemented yet")


def cmd_all(args):
    print("all: not implemented yet")


def cmd_cover(args):
    try:
        cfg = getattr(args, "config_obj", {}) or {}
        out_dir = args.out_dir or ((cfg.get("output", {}) or {}).get("dir") or "output")
        res = run_cover_pipeline(
            args.input,
            cfg,
            out_dir=out_dir,
            dry_run=bool(args.dry_run),
            no_layout=bool(args.no_layout),
            vision=bool(getattr(args, "vision", False)),
        )
        if args.report:
            rep_dir = os.path.dirname(os.path.abspath(args.report))
            if rep_dir:
                os.makedirs(rep_dir, exist_ok=True)
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"output: {res.get('output_path')}")
        if args.report:
            print(f"report: {args.report}")
    except Exception as e:
        print(f"cover failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_libreoffice_toc(args):
    """Build TOC using GutenDocx, then let LibreOffice update fields/TOC.

    Pipeline:
      1) run build_toc(...) to insert a Word TOC field based on Heading styles
      2) call soffice --headless --convert-to docx to let LibreOffice recalc
    """

    try:
        cfg = getattr(args, "config_obj", {}) or {}

        mode = (args.mode or "structured").strip().lower()
        print(f"[libreoffice-toc] build_toc mode={mode}...")
        res_toc = build_toc(args.input, cfg, mode=mode)
        toc_out = res_toc.get("output_path") or args.input
        print(f"[libreoffice-toc] build_toc output: {toc_out}")

        # Determine LibreOffice output dir: by default use output.dir + 'lo_toc'
        out_cfg = (cfg.get("output", {}) or {})
        base_out = out_cfg.get("dir") or "output"
        lo_out_dir = args.out_dir or os.path.join(base_out, "lo_toc")

        soffice_bin = args.soffice or "soffice"
        timeout = int(args.timeout or 120)

        print(
            f"[libreoffice-toc] running LibreOffice: soffice={soffice_bin}, out_dir={lo_out_dir}, timeout={timeout}s"
        )
        res_lo = run_libreoffice_convert(
            toc_out,
            soffice=soffice_bin,
            out_dir=lo_out_dir,
            timeout=timeout,
        )

        ok = bool(res_lo.get("ok"))
        print(f"[libreoffice-toc] LibreOffice ok={ok}, returncode={res_lo.get('returncode')}")
        if res_lo.get("stdout"):
            print("[libreoffice stdout]\n" + res_lo["stdout"].strip())
        if res_lo.get("stderr"):
            print("[libreoffice stderr]\n" + res_lo["stderr"].strip(), file=sys.stderr)

        print(f"[libreoffice-toc] final output: {res_lo.get('output_path')}")
        if not ok:
            sys.exit(1)
    except Exception as e:
        print(f"libreoffice-toc failed: {e}", file=sys.stderr)
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(prog="gutendocx")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("prescan")
    p1.add_argument("input")
    p1.add_argument("--out")
    p1.add_argument("--config", required=False)
    p1.set_defaults(func=cmd_prescan)

    p2 = sub.add_parser("apply-styles")
    p2.add_argument("input")
    p2.add_argument("--config", required=False)
    p2.add_argument("--out", required=False)
    p2.set_defaults(func=cmd_apply_styles)

    p3 = sub.add_parser("layout")
    p3.add_argument("input")
    p3.add_argument("--config", required=False)
    p3.add_argument("--out", required=False)
    p3.set_defaults(func=cmd_layout)

    p4 = sub.add_parser("all")
    p4.add_argument("input", nargs="?")
    p4.add_argument("--input-dir")
    p4.add_argument("--glob", default="*.docx")
    p4.add_argument("--out-dir")
    p4.add_argument("--config", required=False)
    p4.set_defaults(func=cmd_all)

    p5 = sub.add_parser("cover")
    p5.add_argument("input")
    p5.add_argument("--out-dir", required=False)
    p5.add_argument("--dry-run", action="store_true")
    p5.add_argument("--no-layout", action="store_true")
    p5.add_argument("--vision", action="store_true")
    p5.add_argument("--report", required=False)
    p5.add_argument("--config", required=False)
    p5.set_defaults(func=cmd_cover)

    p6 = sub.add_parser("libreoffice-toc")
    p6.add_argument("input")
    p6.add_argument("--mode", required=False)
    p6.add_argument("--soffice", required=False)
    p6.add_argument("--out-dir", required=False)
    p6.add_argument("--timeout", type=int, default=120)
    p6.add_argument("--config", required=False)
    p6.set_defaults(func=cmd_libreoffice_toc)

    return parser


essentials = ["prescan", "apply-styles", "layout", "all", "cover", "libreoffice-toc"]


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        cfg = load_config(getattr(args, "config", None))
    except Exception as e:
        print(f"config load failed: {e}", file=sys.stderr)
        sys.exit(1)
    setattr(args, "config_obj", cfg)
    args.func(args)


if __name__ == "__main__":
    main()
