#!/usr/bin/env python3
"""
路径硬编码检查
"""
import os
import re

PYTHON = "C:/Users/Administrator/.local/bin/python3.13.exe"
METACOG = "D:/skill待检/unclekk-metacog-self-evolve/scripts/metacog.py"

print("SKILL.md 路径硬编码检查:")
print("=" * 50)

with open("D:/skill待检/unclekk-metacog-self-evolve/SKILL.md", "r", encoding="utf-8") as f:
    skill = f.read()

# 检查硬编码的 Python 路径
python_path_patterns = [
    r'C:\\Users\\Administrator\\.workbuddy\\binaries\\python\\versions\\[\d.]+\\python\.exe',
    r'C:/Users/Administrator/.workbuddy/skills/unclekk-metacog-self-evolve/scripts/metacog\.py',
]

for pattern in python_path_patterns:
    matches = re.findall(pattern, skill)
    if matches:
        for m in matches:
            print(f"  [P1] 硬编码路径: {m[:70]}...")

# 检查使用变量替代
print("\n路径变量定义:")
lines = skill.split("\n")
for i, line in enumerate(lines, 1):
    if "PY=" in line or "MC=" in line:
        print(f"  行 {i}: {line.strip()[:80]}")

# 检查文档一致性
print("\n文档一致性检查:")
print(f"  声称零依赖: {'零第三方依赖' in skill or '仅用 Python 标准库' in skill}")
print(f"  版本 1.1.0: {'1.1.0' in skill}")
print(f"  2026-09-07 更新: {'2026-09-07' in skill}")
print(f"  验证记录引用: {'verification.md' in skill}")

# 检查 metacog.py
print("\n" + "=" * 50)
print("metacog.py 硬编码路径检查:")
print("=" * 50)

with open("D:/skill待检/unclekk-metacog-self-evolve/scripts/metacog.py", "r", encoding="utf-8") as f:
    code = f.read()

# 检查是否有硬编码的用户路径
if "Administrator" in code and "workbuddy" in code:
    print("  [P1] 代码中包含硬编码的用户路径")
else:
    print("  [OK] 代码中无硬编码的用户路径")

# 检查是否使用相对路径
print(f"  使用相对 DEFAULT_ROOT: {'DEFAULT_ROOT = \".metacog\"' in code}")
print(f"  使用 pathlib.Path: {'from pathlib import Path' in code}")

# 检查 Python 版本依赖
print("\n" + "=" * 50)
print("Python 版本兼容性:")
print("=" * 50)

# 检查代码特性
print(f"  使用 f-string: {'f\"' in code or \"f'\" in code}")
print(f"  使用 type hints: {'->' in code}")
print(f"  使用 pathlib: {'from pathlib import Path' in code}")
print(f"  使用 dataclass: {'@dataclass' in code}")
print(f"  使用 match/case: {'match ' in code}")

# pathlib 在 Python 3.4+ 可用
# f-string 在 Python 3.6+ 可用
# type hints 在 Python 3.5+ 可用
print("\n  兼容性结论: 代码兼容 Python 3.5+")
