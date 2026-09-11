#!/usr/bin/env python3
"""
paper-humanize 统一 CLI 入口（v2.3）

简化所有功能的调用方式。无需记住每个脚本的参数。

用法：
  python3 cli.py diagnose <text-or-file>      # 诊断单段或整篇
  python3 cli.py advanced <file>               # 高级文档分析（段间/结构/标点/人称）
  python3 cli.py compare <before> <after>      # 改前 vs 改后奖励计算
  python3 cli.py lint <file>                   # 仅扫指纹
  python3 cli.py train <human-dir> <ai-dir>    # χ² 训练词典
  python3 cli.py feedback <file>               # 检测器标红反馈分析
  python3 cli.py help                          # 显示帮助

进阶选项见 score.py / train_dict.py / detector_feedback.py 直接使用。
"""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent


HELP = """\
paper-humanize 统一 CLI（v2.3）

  diagnose <text-or-file> [--section abstract]
      诊断单段文字或整篇 markdown
      若是 .md/.txt 文件 → 跑 diagnose-doc；否则当文本

  advanced <file>
      文档级高级分析（v2.3）：段间一致性 / 结构同质化 / 标点节奏 / 人称混用
      输出比 diagnose 多一个 "advanced" 字段

  compare <before-file> <after-file> [--section abstract]
      改前/改后对比，输出 F/B/E/R 奖励分量 + Gates

  lint <file>
      快速扫描指纹和 register 红线，不算 burstiness

  train <human-dir> <ai-dir> [--top 200]
      χ² 训练自定义指纹库
      产出 candidates.json 或用 --emit-patch 直接生成 score.py 补丁

  feedback <feedback-file> [--top 30]
      从维普/知网检测器标红反馈反向更新指纹库
      用 --emit-patch 生成补丁

  test
      跑测试套件 (tests/test_score.py)

  help
      显示本帮助
"""


def run_subcmd(name: str, args: list[str]) -> int:
    """把子命令转发到对应脚本。"""
    if name == "diagnose":
        if not args:
            print("用法: cli.py diagnose <text-or-file>", file=sys.stderr)
            return 2
        target = args[0]
        rest = args[1:]
        # 自动检测：是文件就走 diagnose-doc，否则走 diagnose --text
        path = Path(target)
        if path.exists() and path.is_file():
            from score import main as score_main
            return score_main(["--mode", "diagnose-doc", "--file", str(path), "--pretty"] + rest)
        else:
            from score import main as score_main
            return score_main(["--mode", "diagnose", "--text", target, "--pretty"] + rest)

    if name == "advanced":
        if not args:
            print("用法: cli.py advanced <file>", file=sys.stderr)
            return 2
        from score import main as score_main
        return score_main(["--mode", "advanced-doc", "--file", args[0], "--pretty"] + args[1:])

    if name == "compare":
        if len(args) < 2:
            print("用法: cli.py compare <before> <after>", file=sys.stderr)
            return 2
        from score import main as score_main
        return score_main([
            "--mode", "compare", "--before", args[0], "--after", args[1], "--pretty"
        ] + args[2:])

    if name == "lint":
        if not args:
            print("用法: cli.py lint <file>", file=sys.stderr)
            return 2
        from score import main as score_main
        return score_main(["--mode", "lint", "--file", args[0], "--pretty"] + args[1:])

    if name == "train":
        if len(args) < 2:
            print("用法: cli.py train <human-dir> <ai-dir>", file=sys.stderr)
            return 2
        from train_dict import main as train_main
        return train_main(["--human", args[0], "--ai", args[1], "--pretty"] + args[2:])

    if name == "feedback":
        if not args:
            print("用法: cli.py feedback <feedback-file>", file=sys.stderr)
            return 2
        from detector_feedback import main as fb_main
        return fb_main(["--feedback", args[0], "--pretty"] + args[1:])

    if name == "test":
        import subprocess
        test_path = SCRIPT_DIR.parent / "tests" / "test_score.py"
        if not test_path.exists():
            print(f"未找到测试: {test_path}", file=sys.stderr)
            return 2
        return subprocess.call([sys.executable, str(test_path)])

    if name in ("help", "-h", "--help"):
        print(HELP)
        return 0

    print(f"未知子命令: {name}\n", file=sys.stderr)
    print(HELP)
    return 2


def main() -> int:
    sys.path.insert(0, str(SCRIPT_DIR))
    if len(sys.argv) < 2:
        print(HELP)
        return 0
    subcmd = sys.argv[1]
    rest = sys.argv[2:]
    return run_subcmd(subcmd, rest)


if __name__ == "__main__":
    sys.exit(main())
