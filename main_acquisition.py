from barakuda.startup import run_app


def main() -> int:
    return run_app(app_mode="acquisition")


if __name__ == "__main__":
    raise SystemExit(main())
