import argparse


def cmd_prescan(args):
    print("prescan: not implemented yet")


def cmd_apply_styles(args):
    print("apply-styles: not implemented yet")


def cmd_layout(args):
    print("layout: not implemented yet")


def cmd_all(args):
    print("all: not implemented yet")


def build_parser():
    parser = argparse.ArgumentParser(prog="wordkit")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("prescan")
    p1.add_argument("input")
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

    return parser


essentials = ["prescan", "apply-styles", "layout", "all"]


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
