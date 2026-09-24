"""仓库路径工具：scripts/ 下任意模块定位仓库根目录内的文件。"""

import os

_SCRIPTS_DIR = os.path.abspath(os.path.dirname(__file__))


def workspace_path(*parts: str) -> str:
    """返回仓库根目录下（可选子路径）的绝对路径。"""
    return os.path.join(os.path.dirname(_SCRIPTS_DIR), *parts)
