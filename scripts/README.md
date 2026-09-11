# scripts/ — 量化打分工具

零依赖（纯 Python 3.8+），无需 pip install。所有 agent 都应**优先调用脚本**而不是自己估算。

## score.py — 核心打分脚本

### 模式 1: diagnose（单段诊断）

供 **Diagnostician** agent 调用，替代手工估算。

```bash
echo "段落文字" | python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode diagnose
# 或
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode diagnose --text "段落文字"
```

输出 JSON 包含：
- `fingerprint_score`：指纹加权分（七档显著度：S+=3，S=2，A=1.5，B=1，C=0.5，D=0.25，E=0.1）
- `fingerprint_hits`：每个匹配的位置 + 显著度
- `burstiness_sigma2`：句长方差
- `burstiness_ratio`：最长/最短句字数比
- `evidence`：数字 / 引用 / 方法学 / 边界 / 黑话 五类痕迹计数
- `register_violations`：8 条 register 红线命中
- `risk`：high / mid / low
- `recommended_axes`：推荐应用哪几个轴

### 模式 2: diagnose-doc（整篇论文）

```bash
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode diagnose-doc --file paper.md --pretty
```

按空行切段，每段独立诊断 + 全文 summary。

### 模式 3: compare（改前 vs 改后）— 核心奖励计算

供 **Reviewer** agent 调用。

```bash
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode compare \
  --before before.txt --after after.txt --pretty
```

输出 `scores.F`、`scores.B`、`scores.E`、`scores.W`、`scores.R_with_default_dQ`，以及四个 gate（`register` / `formality` / `integrity_simple` / `citation_in_review_section`）的 PASS/FAIL。

**Reviewer 工作流**：
1. 跑脚本获得 F / B / E / W / Gates（机械确定）
2. Reviewer 自己只评 ΔQ（语义主观）
3. 用脚本输出 + ΔQ 算最终 R = 0.25·F + 0.20·B + 0.20·E + 0.15·ΔQ + 0.20·W

### 模式 4: lint（仅扫指纹与 register）

快速诊断，不算 burstiness 和 evidence，最快。

```bash
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode lint --file paper.md
```

### 模式 5: advanced-doc（文档级高级分析，v2.3）

```bash
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode advanced-doc --file paper.md --pretty
```

在 diagnose-doc 完整输出的基础上，额外多一个 `advanced` 字段：

- `structural_homogeneity`：段落结构同质化（多对段落开头/结尾雷同）
- `pronoun_consistency`：人称混用检测
- `inter_paragraph`：段间一致性
- `punctuation_rhythm` / `punctuation_signal_score`：标点节奏及其信号分
- `advanced_risk_score`：段落级 AI 信号综合风险增量（0–1，在原有 fingerprint 加权之外）
- `advanced_warnings`：可读的警告清单

### 模式 6: register（书面语度 W + 口语命中，v2.3）

供 **Register Guard** 预筛与交付终检。输入支持 `--text`、`--file` 或 stdin。

```bash
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode register --text "候选段落"
# 或
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode register --file paper.md --pretty
```

输出 JSON 包含：
- `formality_W`：书面语度 W ∈ [0,1]（进奖励公式，占 0.20）
- `w_gate`：W ≥ 0.6 为 PASS，低于 0.6 视同 Register Gate FAIL
- `hits_per_kchar`：每千中文字的口语命中数
- `colloquial_hits`：口语词命中清单（verb / lecture / casual-syntax / symbol 四类）
- `register_violations`：register 红线命中

## cli.py — 统一 CLI 入口

无需记住各脚本参数，子命令自动转发到对应脚本（默认自动加 `--pretty`），额外参数原样透传：

```bash
python3 ~/.claude/skills/paper-humanize/scripts/cli.py diagnose <text-or-file>    # 参数是文件 → diagnose-doc；否则当文本 diagnose
python3 ~/.claude/skills/paper-humanize/scripts/cli.py advanced <file>            # score.py --mode advanced-doc
python3 ~/.claude/skills/paper-humanize/scripts/cli.py compare <before> <after>   # score.py --mode compare
python3 ~/.claude/skills/paper-humanize/scripts/cli.py lint <file>                # score.py --mode lint
python3 ~/.claude/skills/paper-humanize/scripts/cli.py train <human-dir> <ai-dir> # train_dict.py χ² 训练
python3 ~/.claude/skills/paper-humanize/scripts/cli.py feedback <file>            # detector_feedback.py 标红反馈分析
python3 ~/.claude/skills/paper-humanize/scripts/cli.py test                       # 跑 tests/test_score.py
python3 ~/.claude/skills/paper-humanize/scripts/cli.py help                       # 显示帮助
```

透传示例：`cli.py diagnose paper.md --section abstract`、`cli.py feedback feedback.txt --top 30 --emit-patch`。进阶选项直接使用 score.py / train_dict.py / detector_feedback.py。

## detector_feedback.py — 检测器标红反馈分析

用户跑过维普/知网 AIGC 检测后，把标红文字整理成反馈文件（**每行一段标红文字**），脚本对比现有指纹库，找出"漏网"的高频 n-gram，建议补充到 `FINGERPRINTS`。

```bash
# 1. 分析反馈，输出 JSON
python3 ~/.claude/skills/paper-humanize/scripts/detector_feedback.py --feedback feedback.txt --top 20 --pretty

# 2. 直接生成可 copy 到 score.py 的补丁（人工 review 后再合并）
python3 ~/.claude/skills/paper-humanize/scripts/detector_feedback.py --feedback feedback.txt --emit-patch
```

参数：`--feedback`（必填，反馈文件）、`--top`（默认 30）、`--min-count`（默认 2，一个 n-gram 至少出现在 N 段中才算信号）、`--n-min` / `--n-max`（候选 n-gram 长度范围，默认 3–8）、`--emit-patch`、`--pretty`。

输出 JSON 包含：
- `metadata`：反馈段总数、被现有词典覆盖的段数、`current_dict_recall`（现有词典召回率）等
- `missed_patterns`：漏网 n-gram 列表（`ngram`、出现段数、`coverage_ratio`、`score` = 段数 × 长度），已去除被更长候选包含的子串

`--emit-patch` 时按覆盖率与长度自动推断显著度（S+ / S / A / B），生成可直接追加到 `FINGERPRINTS` 的补丁行。

## 脚本与 agent 协作约定

| Agent | 怎么调用脚本 |
|---|---|
| Diagnostician | `--mode diagnose-doc --file <input>`，获得每段 risk + axes，再补语义判断 |
| Axis-A | 改写后用 `--mode diagnose --text <候选>` 自检指纹是否真的下降 |
| Axis-B | 改写后用 `--mode diagnose` 检查 σ² 是否到位（≥150） |
| Axis-C | 改写后用 `--mode diagnose` 检查 evidence 总数是否 ≥ 3 |
| Register Guard | 直接看脚本的 `register_violations` 字段；脚本未命中再做语义判断 |
| Reviewer | `--mode compare` 获得 F/B/E + Gates，自己评 ΔQ |
| Conductor | 全文体检报告用 `--mode diagnose-doc` |

## 局限性（诚实说明）

- **不是真正的 χ² 显著度训练**：当前指纹词库的显著度分档基于经验整理（公开 AIGC 检测器研究 + 真实标红样本），**不是**从 100 篇真实硕博 + 100 篇 GPT 输出统计出来的。
  - 想做真 χ²：用 `train_dict.py` 训练（零依赖，标准库实现），但需要用户提供 human/ai 两组语料目录。

- **句长统计是字符级近似**：没装 jieba 时，用"中文字 + 1每英文词 + 1每数字串"做句长，比真实词数略低估，但比例稳定。装了 jieba 后可加 `--with-jieba` 启用词级分词（默认不启用，保持零依赖）。

- **F/B/E 是确定的，ΔQ 不是**：脚本只算客观指标。"语义连贯""术语精确""论点完整"留给 Reviewer agent，因为这部分需要语义理解。

- **指纹库会过拟合**：长期使用后，agent 可能学会"绕过"脚本（写出脚本检测不到但维普/知网仍标红的 AI 文）。需要持续从用户检测器实测反馈中迭代词库。

## 维护

新发现的高频指纹词追加到 `score.py` 的 `FINGERPRINTS` 列表，按显著度分档。优先级：

1. 用户报告的检测器实测高亮词 → S+
2. 多份 AIGC 检测论文/白皮书共同提及 → S
3. 经验直觉 + 段落级共现强 → A
4. 单源弱信号 → B/C/D
