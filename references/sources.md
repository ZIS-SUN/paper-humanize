# 调研来源

本 skill 的方法论与权重设定基于公开资料的调研整理。诚实标注每条数据/规则的出处，
以便用户判断可信度并自行验证。

## 主要调研来源

### 1. 维普 AIGC 检测机制

**来源**：linggantext.com《维普 AIGC 检测实战攻略 2026》
- URL: https://www.linggantext.com/public/blog/weipu-aigc-detection-guide-2026/
- 抓取时间: 2026-05-02

**采用的关键事实**：

| 项 | 数值 | 在本 skill 的应用 |
|---|---|---|
| 摘要权重 | 1.8 | `SECTION_WEIGHTS["abstract"] = 1.8` |
| 引言/结论/创新点权重 | 1.5-2.0 | `SECTION_WEIGHTS` 取 1.5 |
| 文献综述/方法/结果权重 | 1.0 | 默认 |
| 致谢权重 | 0.5-0.8 | `SECTION_WEIGHTS["ack"] = 0.6` |
| 综述无引用额外 +10-15% AIGC | — | 触发 `citation_penalty` |
| "第一/第二/第三"机械列举 | 强标红信号 | 加入 S+ 档指纹 |
| 摘要"问题导向"结构 + β/p 值 | 实测有效 | 加入 evidence-patterns 模板 |
| 文献综述加"样本限制 + 内生性"批判 | 65% → 35% | 加入 `CRITICAL_PERSPECTIVE_TERMS` |

**注意**：上述权重为该实战攻略给出的经验值，**不是维普官方公布**。维普官方未公开具体加权算法。在 1-3 名用户实测中得到验证，但样本不足以做严格统计。

### 2. 知网 AIGC 检测系统

**来源**：知网官方说明
- URL: https://aicheck.oversea.cnki.net/
- 抓取时间: 2026-05-02

**采用的关键事实**：

- 知网 AIGC 检测从 2023 年 9 月正式上线
- 基于"知识增强 AIGC 检测技术"
- 双链路：语言模式 + 语义逻辑

本 skill 中：知网与维普共用同一套指纹库（差异在权重）；语义逻辑链路对应 burstiness 和段落结构维度。

### 3. humanize-chinese 开源项目（GitHub）

**来源**：https://github.com/voidborne-d/humanize-chinese
- 抓取时间: 2026-05-02

**采用的关键事实**：

- 字符级 trigram 困惑度作为 AI 信号 → 本 skill 未直接采用（需要语料训练 n-gram 表）
- DivEye 惊奇度 → 留待后续版本
- GLTR rank 分桶 → 留待后续版本
- **句长 burstiness 在真人 vs AI 的 Cohen's d = 1.22**（强效应）→ 验证了我们 σ² 阈值的合理性
- 该项目有 20+ 检测维度规则 → 本 skill 已覆盖其中大部分（结构连接、机械列举、空泛副词、模板句）
- 学术专用 126 条替换规则 → 本 skill 在 evidence-patterns.md 给出更聚焦的注入模板

### 4. 中文 AI 文本检测学术研究

**来源 A**：LLM-Detector (arXiv 2402.01158)
- URL: https://arxiv.org/abs/2402.01158
- 内容：基于开源 LLM 指令微调改进中文 AI 文本检测

**来源 B**：基于深度学习的中文 AI 文本检测方法 (AIMS Press 2025)
- URL: https://www.aimspress.com/article/doi/10.3934/bdia.2025016
- 内容：RoBERTa 语义编码 + 手工统计特征双流融合
- **关键发现**：词级分布编码了大部分判别特征 — 即"打乱词序后准确率仅小幅下降" → 验证了"词袋级指纹库"路线（如本 skill）是可行的，无需复杂的语义建模就能达到不错的检测/反检测效果。

### 5. NLPCC 2024 大模型监管评测

**来源**：NLPCC 2024 评测任务通知
- URL: https://blog.csdn.net/c9Yv2cf9I06K2A9E/article/details/137699298

**采用的关键事实**：浙江大学 + 新加坡国立 LLM Regulation 任务（Task 10）涵盖多模态幻觉检测和 LLM 去毒。本任务**不直接**对应中文学术论文 AIGC 检测，但可视为同源研究方向。

## 我们没有的数据，承认局限

以下数据如果有就更好，但目前没有：

- ❌ 100+ 篇真实 CNKI 硕博 + 100+ 篇 GPT 生成对照的语料库 → 没有，所以 χ² 需要用户自己跑（`train_dict.py`）
- ❌ 维普/知网 AIGC 检测器的实际算法 → 它们没公开
- ❌ 用户实测的检测器报告标红样本 → 没有，所以提供 `detector_feedback.py` 让用户自己反推
- ❌ 跨多检测器一致性 ground truth → 不存在公认基准

## 怎么验证 / 怎么改进

如果你想自己验证这套系统的有效性：

1. **横向验证**：拿同一段 AI 生成文本，分别在维普 / 知网 / GPTZero 跑检测，看结果差异 vs 我们的 fingerprint_score 是否相关
2. **纵向验证**：用 paper-humanize 改写后，再过一次维普/知网，看 AIGC 率是否实际下降
3. **校准 SECTION_WEIGHTS**：如果用户多次报告"摘要降的不够"，把 `abstract` 权重从 1.8 调到 2.0
4. **用户反馈环**：每次检测后用 `detector_feedback.py` 喂入标红文字，让指纹库逐步逼近真实检测器关注点

## 维护节奏建议

- **每季度**：检查指纹库末端低 χ² 候选是否仍然有效（检测器可能调整算法）
- **每次用户大批量改写**：用 `train_dict.py` 跑一遍他们的"改后定稿 + 原始 AI 输出"，更新指纹权重
- **每次检测器版本更新**（维普 / 知网 announcement）：用 `detector_feedback.py` 抽样检测前后差异
