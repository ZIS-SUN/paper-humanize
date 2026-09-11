# Agent 调用 Prompt 模板（Conductor 专用）

供 Conductor 在各 Phase 通过 Agent 工具（`subagent_type=general-purpose`）调用子 agent 时使用。
角色定义文件与参考资料在 prompt 里必须传**绝对路径**（`~/.claude/skills/paper-humanize/...`）——
子 agent 的工作目录与本 skill 无关，相对路径会失效。

## 目录

- [Phase 1 — Diagnostician（诊断）](#phase-1--diagnostician诊断)
- [Phase 2 — 三轴并行改写](#phase-2--三轴并行改写)
- [Phase 3 — Register Guard](#phase-3--register-guard)
- [Phase 4 — Reviewer](#phase-4--reviewer)

## Phase 1 — Diagnostician（诊断）

```
你的角色定义见 ~/.claude/skills/paper-humanize/agents/diagnostician.md。
读取该文件并严格按其指示执行。

待诊断文本：
<<<TEXT
{原文，按 §1, §2, §3... 段落编号}
TEXT>>>

参考资料（按需读取）：
- ~/.claude/skills/paper-humanize/references/ai-fingerprint-dict.md

输出 JSON 格式的诊断报告（schema 见你的角色定义）。
```

### 期望产出示例

Diagnostician 返回结构化报告（完整 schema 见 `agents/diagnostician.md`）：

```json
{
  "summary": {
    "total_paragraphs": 24,
    "high_risk": 8,
    "mid_risk": 11,
    "low_risk": 3,
    "locked": 2
  },
  "paragraphs": [
    {
      "id": "§1",
      "risk": "high",
      "fingerprint_count": 7,
      "burstiness_sigma2": 32,
      "evidence_density": 0.0,
      "flags": ["综上所述", "至关重要", "首先...其次...", "随着...的发展"],
      "recommended_axes": ["A", "B", "C"],
      "notes": "通篇空泛，无具体数字、无引用、句长全部 24-32 字，AI 味极浓"
    }
  ]
}
```

## Phase 2 — 三轴并行改写

在**同一个 message 里发出三个 Agent 调用**，并行执行：

```
Agent 1 (subagent_type=general-purpose):
  prompt: "角色定义见 ~/.claude/skills/paper-humanize/agents/axis-a-template-killer.md。
  读取并严格执行。

  待改写段落: <原段落>
  Diagnostician 标注的指纹: <flags from Phase 1>
  锁定不可动的内容: <locked spans>

  参考: ~/.claude/skills/paper-humanize/references/ai-fingerprint-dict.md

  输出: 候选 A（仅做轴 A 改写：消除模板词 + 注入具体所指）"

Agent 2 (subagent_type=general-purpose):
  prompt: "角色定义见 ~/.claude/skills/paper-humanize/agents/axis-b-rhythm-composer.md。
  读取并严格执行。

  待改写段落: <原段落>
  目标 burstiness σ² ≥ 150
  锁定不可动的内容: <locked spans>

  参考: ~/.claude/skills/paper-humanize/references/burstiness-techniques.md

  输出: 候选 B（仅做轴 B 改写：拆 / 合 / 断 三种手法重构句长）"

Agent 3 (subagent_type=general-purpose):
  prompt: "角色定义见 ~/.claude/skills/paper-humanize/agents/axis-c-evidence-injector.md。
  读取并严格执行。

  待改写段落: <原段落>
  原稿参考文献列表: <references list, 用于引用真实性核对>
  原稿数据/参数: <已知 numerics>
  锁定不可动的内容: <locked spans>

  参考: ~/.claude/skills/paper-humanize/references/evidence-patterns.md

  输出: 候选 C（仅做轴 C 改写：注入数字 / 真实引用 / 方法学细节 / 边界条件）"
```

## Phase 3 — Register Guard

调用前 Conductor 先跑 `score.py --mode register` 拿脚本结果（见 SKILL.md Phase 3.1），
把 JSON 原样附进 prompt 的 `script_ground_truth` 字段：

```
Agent (subagent_type=general-purpose):
  prompt: "角色定义见 ~/.claude/skills/paper-humanize/agents/register-guard.md。
  读取并严格执行。

  原段落: <original>
  候选改写: <candidate>
  论文体裁: <thesis_type from Phase 0.2>
  script_ground_truth: <score.py --mode register 的 JSON 输出，原样粘贴>

  参考: ~/.claude/skills/paper-humanize/references/academic-register-redlines.md

  输出 JSON: {verdict: PASS|FAIL, formality_score: 0.X, violations: [...], explanation: '...'}"
```

## Phase 4 — Reviewer

```
Agent (subagent_type=general-purpose):
  prompt: "角色定义见 ~/.claude/skills/paper-humanize/agents/reviewer.md。
  读取并严格执行。

  原段落: <original>
  候选 A (仅轴A改写): <candidate_a>
  候选 B (仅轴B改写): <candidate_b>
  候选 C (仅轴C改写): <candidate_c>
  候选 F (融合版): <candidate_f>

  Diagnostician 报告: <diagnostician output for this paragraph>

  按 5 维奖励公式打分，输出 JSON:
  {
    'scores': {
      'A': {F: 0.X, B: 0.X, E: 0.X, W: 0.X, dQ: 0.X, total: 0.X},
      'B': {...}, 'C': {...}, 'F': {...}
    },
    'winner': 'F',
    'winner_text': '<最终选定的改写>',
    'winner_score': 0.X,
    'reasoning': '...',
    'remaining_issues': ['...'],
    'recommend_iterate': false,
    'integrity_warnings': []
  }"
```

完整评分定义（F/B/E/W/ΔQ 的计算方式与惩罚规则）见 `agents/reviewer.md`。
