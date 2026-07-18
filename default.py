import sys

from lib import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        main.run_configure()
    else:
        main.run()
