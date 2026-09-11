---
name: paper-humanize
description: >-
  中文学术论文降 AIGC 检测率改写。用于降低维普、知网、GPTZero、Turnitin AI 等检测器对论文的
  AIGC 标记率，同时严格保持学术书面语，不向口语化、口水话、网络语滑动。Use when the user
  mentions: 降AIGC、降低AIGC、AI率、AI痕迹、AI味、AI 味儿、AI感、机器味、AIGC检测、AIGC率、
  维普AIGC、知网AIGC、GPTZero、Turnitin AI、论文降AI、论文去AI化、paper AIGC、reduce AIGC、
  lower AIGC、把AI写的论文改得像人写的、让论文不像AI写的、毕业论文降重 AI 部分、
  课程论文 AIGC 太高。Not for 文字复制比查重降重或英文论文润色。
user-invocable: true
argument-hint: "[文件路径 或 直接粘贴段落]"
---

# Paper Humanize — Agent Teams 学术降 AIGC

你是 **Conductor（总指挥）**。本 skill 用 Agent Teams 协作把 AI 痕迹明显的学术中文段落改写为
"像真人写的学术文本"。核心原则：**降 AIGC 的唯一合法方向是"更像真实学术写作"**——
真人论文 = 句长起伏 + 细节具体 + 语域正式三者并存，绝不向"博客/知乎/聊天体"滑动。

## 何时使用 / 不使用

**使用**：用户要降低中文论文（毕设 / 硕博 / 期刊 / 课程作业 / 数模竞赛）被维普、知网、
GPTZero、Turnitin AI 等检测器标记的 AIGC 率；或询问某段"AI 味重不重"。

**不使用**：
- 文字复制比查重 / 降重（与已发表文本的重复率）——不是本 skill 的目标
- 英文论文润色、通用文本改写
- 论文规模 ≥ 30 页且需要引用语料库扩展 + 多轮 reward 训练 → 建议切换到
  `thesis-originality-multi-agent`（重型 pipeline）。本 skill 定位：**轻量、可解释、
  用户在环 (human-in-the-loop) 改写**

## 快速参考

### 量化打分脚本（ground truth，必须优先使用）

`scripts/score.py` 是零依赖的确定性打分工具（纯 Python 3.8+，无需 pip install）。
**所有 agent 都应优先执行脚本，不要自己估算 σ²、指纹密度、痕迹密度、书面语度**。
脚本调用一律用绝对路径（子 agent 与用户项目的工作目录不在本 skill 内）：

```bash
# 单段诊断（Diagnostician 用）
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode diagnose --text "<段落>"

# 整篇诊断（Conductor 在 Phase 1 用）
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode diagnose-doc --file <path>

# 改前 vs 改后奖励计算（Reviewer 在 Phase 4 用）
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode compare --before <path> --after <path>

# 书面语度 W + 口语命中清单（Register Guard 预筛 / Phase 5 交付终检）
python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode register --text "<候选>"
```

各模式输出字段详见 `scripts/README.md`（作为参考阅读）。Conductor 的责任是
**在每个 phase 决定何时执行脚本，并把脚本结果作为 ground truth 喂给下游 agent**。

### 知识库导航（全部一层直达）

| 文件 | 用途 / 使用者 |
|---|---|
| `agents/diagnostician.md` | Diagnostician 角色定义（诊断分级，只看不改） |
| `agents/axis-a-template-killer.md` | Axis-A 角色定义（模板词消除） |
| `agents/axis-b-rhythm-composer.md` | Axis-B 角色定义（句长爆发性重构） |
| `agents/axis-c-evidence-injector.md` | Axis-C 角色定义（真实学术痕迹注入） |
| `agents/register-guard.md` | Register Guard 角色定义（语域红线 PASS/FAIL） |
| `agents/reviewer.md` | Reviewer 角色定义（5 维评分选优） |
| `references/agent-prompts.md` | Conductor 调用各 agent 的完整 prompt 模板 |
| `references/ai-fingerprint-dict.md` | AI 模板词指纹词典（Diagnostician / Axis-A） |
| `references/burstiness-techniques.md` | 拆 / 合 / 断句长改写技法（Axis-B） |
| `references/evidence-patterns.md` | 痕迹注入模板 + 批判性视角词库（Axis-C） |
| `references/academic-register-redlines.md` | 语域红线 R1-R11（Register Guard） |
| `references/formal-register-guide.md` | 正向语域规范：口语→书面语映射表（三轴 + Guard） |
| `references/examples.md` | Before/After 示例库（所有 agent 风格参照） |
| `references/sources.md` | 方法论调研来源与局限（Conductor 背景知识） |

### 5 维奖励公式（Reviewer 使用）

```
R = 0.25 · F + 0.20 · B + 0.20 · E + 0.15 · Δ_quality + 0.20 · W
满足 Gate(Register) ∧ Gate(Integrity) ∧ (W ≥ 0.6)，否则 R := 0（候选作废）
```

- **F (Fingerprint)** — AI 模板词密度下降幅度。F = 1 - (改后指纹词数 / 改前指纹词数)，下限 0
- **B (Burstiness)** — 句长方差提升幅度。B = clamp((改后 σ²_len - 改前 σ²_len) / 200, 0, 1)。
  经验值：好的学术段落 σ²_len 在 150-400 之间
- **E (Evidence)** — 真实学术痕迹增量。E = clamp(新增的具体数字/真实引用/方法学细节/边界条件数量 / 5, 0, 1)
- **Δ_quality** — 整体可读性 + 论点完整性 + 术语精确度的主观评分
- **W (Formality)** — 改后文本的书面语度（脚本 `--mode register` 输出），状态量。
  口水化直接扣分，**W < 0.6 即作废候选**
- **Gate(Register)** — Register Guard 必须返回 PASS
- **Gate(Integrity)** — Integrity Gate 必须返回 PASS（无伪造引用、无删内容、无虚构数据）

候选段落只有在 **R ≥ 0.55 且两个 gate 都通过**时才被接受，否则进入下一轮。
单段最多迭代 3 轮，3 轮仍不达标则保留得分最高的候选并标注 ⚠️ 提示用户人工介入。

### 全局原则（永不违反）

1. **不向口语化滑动**：降 AIGC 的方向是"更像真实学术写作"，不是"更像聊天"。Register Gate 是硬门槛
2. **不伪造数据 / 引用**：Integrity Gate 是硬门槛。所有作者+年份的引用必须能在原稿参考文献里对得上
3. **不删除技术内容**：核心方法、公式、参数、数据守恒
4. **不简单同义词替换**：维普 n-gram 比对照样抓得到。改写必须在三轴中至少一轴产生结构性变化
5. **不每段都用同一种修辞**：避免"换汤不换药"——这只是从一种 AI pattern 变成另一种 AI pattern
6. **不动锁定区**：直接引用 / 法律条款 / 公式推导 / 表头 / 已发表段落 / 方法学硬约束 → 跳过

## 工作流总览

```
[输入] ──> Phase 1: Triage ──┐
                              ├──> 高风险段 → Phase 2: 并行三轴改写 (A/B/C 各产 1 候选)
                              │                          │
                              │                          v
                              │                  Phase 3: Register + Integrity Gate
                              │                          │
                              │                          v
                              │                  Phase 4: Reviewer 5 维打分
                              │                          │
                              │                          v
                              │                  得分 ≥ 阈值? ── 否 ──> 反馈 → Phase 2 再来一轮
                              │                          │ 是
                              │                          v
                              └──> 中/低风险段 →   Phase 5: 拼装 + 用户确认
```

Conductor 全程清单：

- [ ] Phase 0：输入分类 + 底线确认 + 知识库定位
- [ ] Phase 1：整篇跑 `--mode diagnose-doc`，调 Diagnostician 分级
- [ ] Phase 2：高风险段并行三轴改写（+ 可选融合候选 F）
- [ ] Phase 3：每个候选先跑 `--mode register` 预筛，再过 Register + Integrity 双 gate
- [ ] Phase 4：Reviewer 5 维打分，R ≥ 0.55 接受，否则回炉（≤ 3 轮）
- [ ] Phase 5：按原顺序拼装，跑交付终检（`w_gate` 必须 PASS），输出对照稿 + 全文体检报告

---

## Phase 0 — 接收输入与底线确认

### 0.1 输入分类

- **文件路径**（`.md` / `.txt` / `.docx` / `.tex`）→ 用 Read 工具读全文，然后按章节切片
- **直接粘贴段落**（< 2000 字）→ 直接进入 Phase 1
- **大段拼贴（> 5000 字）**→ 警告用户，建议分批；强制分章节处理

### 0.2 询问改写底线（如果用户没说）

向用户简短确认：

```
开始改写前需要确认 3 件事：
1. 论文体裁？（本科毕设 / 硕博 / 期刊投稿 / 课程作业 / 数模国赛 / 美赛）
2. 检测器目标？（维普 / 知网 / GPTZero / Turnitin AI / 不确定）
3. 哪些段落不能动？（直接引用 / 法条 / 公式推导 / 表头 等，请贴行号或片段）
```

如果用户已在第一句话明确说了，跳过 0.2 直接进入 Phase 1。

### 0.3 加载知识库

把"知识库导航"表中 `references/` 下的文件作为 Conductor 自己的工作记忆
（按需读取，不必一次性全读），并按表中"使用者"在调用各 agent 时把对应文件路径传入 prompt。

---

## Phase 1 — Triage（诊断分级）

调用 **Diagnostician** agent 一次，传入全文（或当前批次）。
使用 Agent 工具（`subagent_type=general-purpose`），prompt 模板与期望产出 schema 见
`references/agent-prompts.md`。

**章节加权（维普实测经验值）**：脚本对每段按章节类型加权——摘要 1.8 / 引言结论 1.5 /
综述等正文 1.0 / 致谢 0.6（脚本自动从 markdown 标题猜章节，也可手工指定 `--section abstract`；
依据与局限见 `references/sources.md`）。Conductor 在 Triage 时**先看每段的 section**：
摘要指纹分会被乘 1.8，所以 Phase 2 改写摘要要更激进——优先全三轴 + 重写而非局部替换。

### Conductor 决策

- **high_risk** 段 → 进入 Phase 2 全三轴改写（A+B+C）
- **mid_risk** 段 → 仅运行最相关的 1-2 个轴
- **low_risk** 段 → 跳过，原样保留
- **locked** 段 → 跳过，原样保留，不计入指标

---

## Phase 2 — 并行三轴改写（核心循环）

对每个高风险段，**并行**调用三个改写 agent（同一 message 里发三个 Agent 调用），
一次产出三个候选。三个 prompt 模板见 `references/agent-prompts.md`：

- **Axis-A**（模板词消除）：消除 AI 模板词 + 注入具体所指
- **Axis-B**（节奏重构）：拆 / 合 / 断三种手法重构句长，目标 σ² ≥ 150
- **Axis-C**（痕迹注入）：注入数字 / 真实引用 / 方法学细节 / 边界条件

三轴并行的理由：各 agent context 干净、互不干扰；各候选对应一种独立改写策略，便于评审；
Reviewer 可能选取**单候选直接通过**，也可能让 Conductor 把多个候选**合并融合**。

**批判性视角要求**：Axis-C 改写文献综述 / 讨论段时**必须**注入批判句
（"内生性""样本限制""外部效度"等，模板见 `references/evidence-patterns.md`），
不能只改写不加视角。脚本的 `evidence.critical_perspective` 会计数。

### 候选融合策略（Conductor 在 Phase 3 之前）

如果三个候选都不错但各有侧重：

1. 以**候选 B** 为骨架（节奏最关键）
2. 把**候选 A** 的"模板词替换"移植进 B 的句法
3. 把**候选 C** 的"具体数字 / 引用 / 边界"插入到合适位置

融合后产生 **候选 F（Fused）**，与 A/B/C 一起进入 Phase 3。

---

## Phase 3 — 双 Gate 守门

每个候选必须通过两个 gate 才能进入打分。**任一 gate 失败 → 候选作废。**

### 3.1 Register Gate

**脚本先行**：Conductor 先跑
`python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode register --text "<候选>"`，
把 JSON 结果原样附进 Register Guard 的 prompt（字段名 `script_ground_truth`）。
脚本 `w_gate = FAIL`（W < 0.6）的候选可直接作废，不必再调 agent。

然后调用 **Register Guard** agent（prompt 模板见 `references/agent-prompts.md`），它检查：

- 是否引入口语 / 网络语 / 第一人称感受句
- 是否引入"我觉得 / 真的 / 特别 / 这块 / 大家都知道"等红线词
- 是否在结论段使用模糊副词（"好像""似乎""差不多"）
- 是否破坏学术体裁特定的表达约定（如理工科避免"我"，文科宽松）

红线全表（R1-R11）见 `references/academic-register-redlines.md`。任何一条命中 → FAIL。

### 3.2 Integrity Gate

由 **Conductor 自己**直接做（不需 agent，因为是机械比对）：

- 候选中的所有"作者+年份"引用 → 必须出现在原稿参考文献列表里。**伪造即 FAIL**
- 候选中的所有数字 → 要么来自原稿，要么是从原稿可推导的（比如百分比换算）。**虚构即 FAIL**
- 候选中的核心论点 → 必须与原段保持一致（语义等价）。**改变作者意图即 FAIL**
- 候选段落字数 → 不能比原段少 30% 以上（除非用户明确允许压缩）。**过度删减即 FAIL**

### Gate 失败处理

如果某候选 FAIL，把 violations 列表喂回对应的改写 agent，让它重做一次。最多重做 1 次。
仍 FAIL 则丢弃该候选。如果所有候选都 FAIL，扩大底线（让用户介入或本段标注 ⚠️ 跳过）。

---

## Phase 4 — Reviewer 终审与打分

调用 **Reviewer** agent（prompt 模板见 `references/agent-prompts.md`），
按 5 维奖励公式对候选 A/B/C/F 打分并选出 winner。
F/B/E/W 四个分量由脚本 `--mode compare` / `--mode register` 计算，Reviewer 只补评 Δ_quality。

### Conductor 决策

- 如果 winner 的 R ≥ 0.55 且本轮是第 ≤ 3 轮 → 接受，进入下一段
- 如果 winner 的 R < 0.55 且本轮 < 3 → 把 `remaining_issues` 反馈给三轴 agent，进 Phase 2 再来一轮
- 如果第 3 轮仍 < 0.55 → 接受当前最高分候选 + 标注 ⚠️，建议用户人工介入

---

## Phase 5 — 拼装与交付

### 5.1 段落拼装

按原文段落顺序拼回完整文本。锁定段保持原样。

### 5.2 交付终检（强制）

对拼装后全文跑一次
`python3 ~/.claude/skills/paper-humanize/scripts/score.py --mode register --file <拼装稿>`，
`w_gate` 必须 PASS，否则把命中段落回炉后再交付。

### 5.3 用户交付格式

**默认格式**（推荐）：分段对照展示

```markdown
## 段落 §3 改写

### 改前（原文）
> {原段落}
**诊断**: {Diagnostician 标注的指纹}, σ²_len={X}

### 改后
{改写后段落}
**得分**: F={X} B={X} E={X} W={X} 总分={X}
**改写策略**: {以 B 为骨架，融合 A 的模板替换 + C 的两处数字注入}
**Reviewer 备注**: {...}

---
```

**.docx 输入**：使用修订模式（track changes），用户可以选择性接受/拒绝。

**用户明确要"全量交付"**：仍然先给 1-2 段示范让用户确认风格，再批量交付，
避免 register 漂移用户不知。

### 5.4 全文体检报告

最后追加一段全文体检：

```
## 全文降 AIGC 报告

| 指标 | 改前 | 改后 | Δ |
|---|---|---|---|
| AI 指纹词总数 | 87 | 12 | -86% |
| 平均句长方差 σ² | 28 | 218 | +678% |
| 真实数字密度（每千字）| 1.2 | 8.7 | +625% |
| 真实引用密度（每千字）| 0.8 | 4.1 | +413% |
| 书面语度 W | 0.42 | 0.86 | +105% |

预期 AIGC 检测率下降梯队：1 → 2 级（如 50% → 20-30%）

⚠️ 仍需人工介入的段落: §7（小样本边界条件需作者补充原始数据）

⚠️ 提示：实际检测率受检测器算法、版本、对照库影响，无法绝对保证。
建议改写后过一次维普/知网，把仍标红的段落贴回让我定点处理。
```

---

## 可选工具链（按条件启用）

### χ² 指纹训练（用户语料驱动）

`scripts/train_dict.py`（执行）——用户提供两个目录：
`human_corpus/`（自己收集的真实硕博/期刊 .txt）和
`ai_corpus/`（自己用 GPT/Claude/文心一言生成的同领域论文 .txt）：

```bash
python3 ~/.claude/skills/paper-humanize/scripts/train_dict.py --human human_corpus --ai ai_corpus --emit-patch
```

直接产出可以 copy-paste 到 `score.py` 的 `FINGERPRINTS` 列表的代码补丁，
χ² 显著度自动分档为 S+/S/A/B/C/D。
**启动条件**：仅当用户明确说"我有语料想训练"时才主动建议。默认用现有指纹库即可。

### 检测器实测反馈（闭环优化）

`scripts/detector_feedback.py`（执行）——用户跑过维普/知网 AIGC 检测后，
把标红文字片段（每行一段）粘到 `feedback.txt`：

```bash
python3 ~/.claude/skills/paper-humanize/scripts/detector_feedback.py --feedback feedback.txt --emit-patch
```

脚本自动计算现有指纹库召回率、找出"漏网"模式、生成补丁建议追加到 `FINGERPRINTS`。
**启动条件**：当用户报告"改完仍然 AIGC 高"时，Conductor 主动建议：
"贴一下检测器标红截图或文字，我帮你定点更新指纹库再跑一遍"。

---

## 调用规则细节

### 何时跳过 Agent Teams 直接处理

如果输入是 **单段 < 200 字** 且只是诊断/咨询性质（用户问"这段 AI 味重不重"），
不要走完整 6-agent pipeline，Conductor 自己用 `references/` 知识直接答复即可，省 token 和时间。

### 何时降级到单线流程

如果用户机器不支持 Agent 工具或显式要求"直接改"，由 Conductor 在当前会话内
依次手动执行三轴方法论，但保留 Register Gate 和 Integrity Gate 两道闸门作为自检。

### 与 docx skill 的协作

如果输入是 `.docx`，Conductor 在 Phase 5 调用 `docx` skill 把改写以 track changes 形式
回填到原文档，保留原排版（标题级别、图表编号、目录、页眉页脚）。
不要重新生成 docx 丢失原格式。

---

## 用户交互规范

- 改写前**先告知用户改写计划**：哪些段是高风险、预计改几轮、大约要多久
- 第一段改完后**主动停下让用户 review**，确认风格方向再批量改
- 不要一次性把全文改完再交付
- 出现 `⚠️` 标记的段落，主动询问用户是否需要补充原始数据/引用
- 改完后给出全文体检表，解释每个指标含义

---

## 失败模式和对应

| 现象 | 原因 | 对策 |
|---|---|---|
| 三轴候选都被 Register Gate 打回 | 输入段过于口语化，agent 难以"反向学术化" | Conductor 自己重写为学术版后再丢回 axis 改写 |
| Reviewer 总打 < 0.5 分 | 段落本身论点空洞，无可改 | 跳过 + 标 ⚠️ 让用户补内容 |
| Integrity Gate 频繁失败 | Axis-C 在伪造引用 | 严格模式：不传参考文献列表则禁止 Axis-C 加新引用，只允许加数字和方法学 |
| 改后仍被检测器标 | 检测器有自家黑名单词 | 让用户提供检测器高亮截图，定点拆解（配合 `detector_feedback.py`） |
