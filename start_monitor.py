#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五分钟话术监控系统启动器
"""

import sys
import os
from pathlib import Path

# 添加src目录到Python路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from five_minute_monitor.start_five_minute_monitor import main

if __name__ == "__main__":
    main()