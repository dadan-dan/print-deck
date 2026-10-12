"""打包入口：保持绝对导入，避免 PyInstaller 下相对导入失效。"""

import sys

from printdeck.cli import main

if __name__ == "__main__":
    sys.exit(main())
