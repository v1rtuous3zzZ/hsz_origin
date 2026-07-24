import runpy
import sys

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "nightly-check", *sys.argv[1:]]
    runpy.run_module("app.etl.cli", run_name="__main__")
