import argparse
import json
import os
import sys

from ..core.scan import prescan as scan_prescan
from ..core.config import load_config
from ..core.cover import run_cover_pipeline


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
        res = run_cover_pipeline(args.input, cfg, out_dir=out_dir, dry_run=bool(args.dry_run))
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
    p5.add_argument("--report", required=False)
    p5.add_argument("--config", required=False)
    p5.set_defaults(func=cmd_cover)

    return parser


essentials = ["prescan", "apply-styles", "layout", "all", "cover"]


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
