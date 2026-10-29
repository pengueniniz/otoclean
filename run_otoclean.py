"""PyInstaller giriş noktası (paket içi göreli import'lar için ayrı başlatıcı)."""

import sys

from otoclean.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
