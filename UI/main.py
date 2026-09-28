"""Entry point of the desktop app (the packaged exe starts here; `python main.py` in development).

multiprocessing.freeze_support() has to run before app.py is imported: the game watcher runs in a
child process that starts this same program, and app.py does its startup work (web server, packet
capture, the OCR worker) at import. Called first, freeze_support() turns the child into just the
worker it should be instead of a second copy of the whole app.
"""
import multiprocessing


def run():
    multiprocessing.freeze_support()
    import app  # noqa: PLC0415 - only after freeze_support, see above
    app.main()


if __name__ == "__main__":
    run()
