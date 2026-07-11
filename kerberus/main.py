from .instance import acquire_single_instance, notify_already_running
from .ui import run


def main() -> None:
    if not acquire_single_instance():
        notify_already_running()
        return
    run()


if __name__ == "__main__":
    main()
