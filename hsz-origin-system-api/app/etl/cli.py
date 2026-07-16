import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="ETL 独立命令入口（本阶段未执行同步）")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("live", "live-once", "backfill", "status"):
        subparsers.add_parser(command)
    parser.parse_args()


if __name__ == "__main__":
    main()
