# paper-humanize

中文学术论文降 AIGC 检测率改写技能（Claude / Agent Skill 格式）。用于降低维普、知网、
GPTZero、Turnitin AI 等检测器对论文的 AIGC 标记率，同时严格保持学术书面语。

**核心原则**：降 AIGC 的唯一合法方向是"更像真实学术写作"——
真人论文 = 句长起伏（burstiness）+ 细节具体 + 语域正式三者并存，
绝不向"博客 / 知乎 / 聊天体"滑动。

## 适用 / 不适用

**适用**：降低中文论文（毕设 / 硕博 / 期刊 / 课程作业 / 数模竞赛）被检测器标记的
AIGC 率，或评估某段"AI 味重不重"。触发词：降AIGC、AI率、AI味、论文降AI、论文去AI化等。

**不适用**：

- 文字复制比查重 / 降重（与已发表文本的重复率）
- 英文论文润色、通用文本改写
- 论文规模 ≥ 30 页的重型需求（可扩展为多 agent 重型 pipeline）

## 工作原理

采用 6 角色 Agent Teams 协作（human-in-the-loop）：

| 角色 | 职责 |
|---|---|
| Conductor | 总指挥：分诊、调度、Integrity Gate、拼装交付 |
| Diagnostician | 诊断分级：标注 AI 指纹，输出 high/mid/low/locked |
| Axis-A（template-killer） | 消除 AI 模板词 + 注入具体所指 |
| Axis-B（rhythm-composer） | 拆 / 合 / 断句长重构，目标句长方差 σ² ≥ 150 |
| Axis-C（evidence-injector） | 注入数字 / 真实引用 / 方法学细节 / 边界条件 |
| Register Guard | 语域红线 R1-R11 检查（PASS/FAIL） |
| Reviewer | 5 维奖励公式打分选优 |

对每个高风险段并行产出 A/B/C 三个候选，经 **Register Gate + Integrity Gate** 双闸门，
按 5 维公式打分：

```
R = 0.25·F(指纹下降) + 0.20·B(句长方差) + 0.20·E(真实痕迹) + 0.15·Δ_quality + 0.20·W(书面语度)
Gate(Register) ∧ Gate(Integrity) ∧ (W ≥ 0.6)，否则 R := 0
```

R ≥ 0.55 才接受候选；单段最多迭代 3 轮，仍不达标则保留最高分候选并标注 ⚠️。

## 硬门槛（永不违反）

1. **不向口语化滑动**——Register Gate 硬门槛
2. **不伪造数据 / 引用**——Integrity Gate 硬门槛
3. **不删除技术内容**——方法、公式、参数、数据守恒
4. **不简单同义词替换**——改写须在至少一轴产生结构性变化
5. **不动锁定区**——直接引用 / 法条 / 公式推导 / 表头跳过

## 量化打分脚本

`scripts/score.py` 是零依赖的确定性打分工具（纯 Python 3.8+，无需 pip install）：

```bash
# 单段诊断
python3 scripts/score.py --mode diagnose --text "<段落>"

# 整篇诊断
python3 scripts/score.py --mode diagnose-doc --file <path>

# 改前 vs 改后奖励计算
python3 scripts/score.py --mode compare --before <path> --after <path>

# 书面语度 W + 口语命中清单
python3 scripts/score.py --mode register --text "<候选>"
```

## 目录结构

```
SKILL.md                            # 技能主文档（Conductor 完整工作流）
agents/                             # 6 个角色的定义
references/                         # 指纹词典、改写技法、语域红线、示例库、调研来源
scripts/                            # score.py 打分、train_dict.py 指纹训练、detector_feedback.py 检测器反馈
tests/                              # 打分脚本测试
```

## 可选工具链

- **χ² 指纹训练**（`scripts/train_dict.py`）：提供真实人写语料 `human_corpus/` 与
  AI 生成语料 `ai_corpus/` 两个目录，产出可直接贴进 `score.py` 的指纹库补丁。
- **检测器反馈闭环**（`scripts/detector_feedback.py`）：改写后仍被标红时，把检测器
  高亮片段贴入 `feedback.txt`，脚本计算召回率并生成指纹库补丁。

## 使用方式

将本目录放入 Claude 技能目录（如 `~/.claude/skills/paper-humanize`），然后在会话中
`/paper-humanize <文件路径 或 直接粘贴段落>` 即可。完整工作流见 [SKILL.md](SKILL.md)。

> 免责声明：实际检测率受检测器算法、版本、对照库影响，无法绝对保证；
> 使用前请确认符合所在机构对 AI 辅助写作的规定。
