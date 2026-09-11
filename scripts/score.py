#!/usr/bin/env python3
"""
paper-humanize v2.3 量化打分脚本

确定性输出 F (Fingerprint) / B (Burstiness) / E (Evidence) / W (Formality) 四维指标 + 详细诊断 JSON。
零依赖：Python 3.8+ 标准库；jieba 可选（用 --with-jieba 启用更准确的词级分词）。

v2.3 新增（语域锚定，防口水化）：
- COLLOQUIAL_PATTERNS 口语词表（verb/lecture/casual-syntax/symbol 四类）
- 书面语度 W ∈ [0,1]，进奖励公式（占 0.20）；W < 0.6 视同 Register Gate FAIL
- --mode register：输出 W + 口语命中清单，供 Register Guard 预筛与交付终检

v2.2 新增（基于调研）：
- 章节加权（维普实测：摘要 1.8 / 引言结论 1.5 / 综述 1.0 / 致谢 0.6）
- 机械列举检测（"第一/第二/第三"、"一是/二是/三是"等）
- 缺引用惩罚（综述类无引用 → AIGC 检测率额外 +10-15%）
- 指纹词扩充至 100+ 条（含调研发现的新模板）
- 修复重叠匹配 bug（去重相同跨度的多重命中）
- jieba 可选词级分词

用法：
  echo "段落" | python3 score.py --mode diagnose
  python3 score.py --mode diagnose --text "..." --section abstract
  python3 score.py --mode diagnose-doc --file paper.md
  python3 score.py --mode compare --before a.txt --after b.txt --section abstract
  python3 score.py --mode lint --file paper.md
  python3 score.py --mode register --text "候选段落"   # 书面语度 W + 口语命中清单（v2.3）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# 可选 jieba 增强（默认不启用，保持零依赖）
_JIEBA = None
try:
    import jieba as _jieba_mod  # type: ignore
    _JIEBA = _jieba_mod
except ImportError:
    pass


# ---------- 章节加权（v2.2 新增）----------
# 来源：维普 AIGC 检测官方机制 + linggantext 2026 实测攻略
# 高权重区段被检测得更严，要求改写更激进
SECTION_WEIGHTS: dict[str, float] = {
    "abstract": 1.8,        # 摘要：权重最高
    "intro": 1.5,           # 引言
    "introduction": 1.5,
    "conclusion": 1.5,      # 结论
    "innovation": 1.5,      # 创新点
    "contribution": 1.5,    # 贡献
    "literature_review": 1.0,  # 文献综述
    "method": 1.0,          # 方法
    "experiment": 1.0,      # 实验
    "results": 1.0,         # 结果分析
    "discussion": 1.0,      # 讨论
    "default": 1.0,
    "background": 0.7,      # 研究背景
    "theory": 0.7,          # 理论基础
    "ack": 0.6,             # 致谢
    "acknowledgments": 0.6,
}


# ---------- AI 指纹词典（v2.2 扩充至 100+ 条）----------
# 七档显著度: S+ > S > A > B > C > D > E
# 权重: S+=3, S=2, A=1.5, B=1, C=0.5, D=0.25, E=0.1
SIGNIFICANCE_WEIGHT = {"S+": 3.0, "S": 2.0, "A": 1.5, "B": 1.0, "C": 0.5, "D": 0.25, "E": 0.1}

FINGERPRINTS: list[tuple[str, str, str]] = [
    # ==================== S+ 档：维普/知网 AIGC 模块明确高亮 ====================
    # 结构连接
    (r"综上所述", "S+", "结构连接"),
    (r"由此可见", "S+", "结构连接"),
    (r"总而言之", "S+", "结构连接"),
    (r"综上而言", "S+", "结构连接"),
    (r"一言以蔽之", "S+", "结构连接"),
    (r"值得注意的是", "S+", "结构连接"),
    (r"不可忽视的是", "S+", "结构连接"),
    (r"不容忽视", "S+", "结构连接"),
    # 评价拔高
    (r"至关重要", "S+", "评价拔高"),
    (r"具有重要意义", "S+", "评价拔高"),
    (r"具有重大意义", "S+", "评价拔高"),
    (r"发挥重要作用", "S+", "评价拔高"),
    # 伪具体
    (r"在某种程度上", "S+", "伪具体"),
    (r"一定程度上", "S+", "伪具体"),
    (r"某种意义上", "S+", "伪具体"),
    # v2.2 新增：机械列举（维普标记的强信号）
    (r"首先.{0,40}其次.{0,80}(再次|然后).{0,80}最后", "S+", "结构连接"),
    (r"首先.{0,40}其次.{0,80}最后", "S+", "结构连接"),
    (r"第一.{0,40}第二.{0,80}第三", "S+", "结构连接"),       # 新增
    (r"一是.{0,40}二是.{0,80}三是", "S+", "结构连接"),       # 新增
    (r"一方面.{0,80}另一方面", "S+", "结构连接"),            # 新增
    # 背景模板
    (r"随着.{0,15}的(快速)?发展", "S+", "背景模板"),
    (r"在.{0,15}的背景下", "S+", "背景模板"),

    # ==================== S 档：高频 AI 标记 ====================
    (r"奠定(了)?(?:.{0,10})?基础", "S", "评价拔高"),
    (r"提供(了)?保障", "S", "评价拔高"),
    (r"保驾护航", "S", "评价拔高"),
    (r"深远(的)?影响", "S", "评价拔高"),
    (r"不可替代", "S", "评价拔高"),
    (r"不容小觑", "S", "评价拔高"),
    (r"极具.{1,4}价值", "S", "评价拔高"),
    (r"取得了显著(的)?(?:成果|效果|进展)", "S", "评价拔高"),
    (r"取得了优异(的)?(?:成果|效果|成绩)", "S", "评价拔高"),
    (r"具有重要(的)?(理论价值|实际意义|应用价值|参考价值)", "S", "评价拔高"),
    (r"广泛(地)?应用", "S", "空泛副词"),
    (r"得到(了)?广泛", "S", "空泛副词"),
    (r"深入(地)?(研究|探讨|分析|思考|挖掘)", "S", "空泛副词"),
    (r"全面(地)?(分析|评估|考察|阐述)", "S", "空泛副词"),
    (r"有效(地)?(提升|改善|解决|缓解)", "S", "空泛副词"),
    (r"显著(地)?(提升|改善|优化|提高)", "S", "空泛副词"),
    (r"进一步(的)?(?:研究|探讨|分析|完善|优化)", "S", "空泛副词"),
    (r"近年来", "S", "背景模板"),
    (r"当今(信息化)?时代", "S", "背景模板"),
    (r"现如今", "S", "背景模板"),
    (r"在.{0,15}的(浪潮|大潮|趋势)下", "S", "背景模板"),
    # v2.2 新增：常见结尾模板
    (r"不断(完善|优化|提升|加强|改进)", "S", "评价拔高"),
    (r"为.{0,15}的发展做出.{0,5}贡献", "S", "评价拔高"),
    (r"推动.{0,15}的(?:健康|稳步|蓬勃)?发展", "S", "评价拔高"),

    # ==================== A 档：常见 AI 习惯 ====================
    (r"与此同时", "A", "结构连接"),
    (r"在此基础上", "A", "结构连接"),
    (r"归根结底", "A", "结构连接"),
    (r"毫无疑问", "A", "结构连接"),
    (r"不言而喻", "A", "结构连接"),
    (r"特定情况下", "A", "伪具体"),
    (r"相关(问题|研究|方法|工作|领域)", "A", "伪具体"),
    (r"对应(的)?", "A", "伪具体"),
    (r"相应(的)?", "A", "伪具体"),
    (r"所谓(的)?", "A", "伪具体"),
    (r"一些(研究|学者|工作|方法)", "A", "伪具体"),
    (r"部分(研究者|学者|工作)", "A", "伪具体"),
    (r"许多(研究|学者)", "A", "伪具体"),
    (r"大量(研究|工作)", "A", "伪具体"),
    (r"做出.{0,8}贡献", "A", "评价拔高"),
    (r"做出更大的贡献", "A", "评价拔高"),
    (r"为.{0,15}的发展(做出|提供)", "A", "评价拔高"),
    (r"推动.{0,15}的发展", "A", "评价拔高"),
    # v2.2 新增：AI 标准过渡
    (r"为此", "A", "结构连接"),
    (r"鉴于此", "A", "结构连接"),
    (r"综观全局", "A", "结构连接"),
    (r"在新形势下", "A", "背景模板"),
    (r"步入新时代", "A", "背景模板"),

    # ==================== C 档：论文模板（少量出现 OK）====================
    (r"本文将从.{0,20}入手", "C", "论文模板"),
    (r"本研究旨在", "C", "论文模板"),
    (r"本节将详细介绍", "C", "论文模板"),
    (r"本文结构如下", "C", "论文模板"),
    (r"接下来(将)?(分析|讨论|介绍)", "C", "论文模板"),
    (r"下面(将)?(分析|讨论|介绍)", "C", "论文模板"),

    # ==================== D 档：低显著但仍可疑 ====================
    (r"广泛(地)?", "D", "空泛副词"),
    (r"充分(地)?(发挥|利用|体现)", "D", "空泛副词"),
    (r"合理(地)?", "D", "空泛副词"),
    (r"科学(地)?", "D", "空泛副词"),
    (r"较好(地)?", "D", "空泛副词"),
    (r"更好(地)?", "D", "空泛副词"),
]

# 抽象后缀堆砌（≥ 2 共现才计 1 个 B 档）
ABSTRACT_SUFFIX_HUA = ["系统化", "规范化", "标准化", "智能化", "信息化", "个性化",
                       "网络化", "数字化", "模块化", "自动化"]
ABSTRACT_SUFFIX_XING = ["重要性", "必要性", "可行性", "合理性", "有效性", "稳定性",
                        "复杂性", "多样性", "普适性"]

# ---------- Register 红线 ----------
REGISTER_REDLINES: list[tuple[str, str, str]] = [
    (r"我觉得|我感觉|我以为", "R1", "第一人称感受词"),
    (r"大家都知道|大家都明白|众所周知", "R1", "假设读者已知"),
    (r"在我看来", "R1", "第一人称视角"),
    (r"通过我的努力|经过我的努力", "R1", "第一人称努力描述"),
    (r"真的(很|是)?(?![一-鿿])", "R2", "口语强调副词"),
    (r"实在是", "R2", "口语强调"),
    (r"超级(?![一-鿿])|巨好|巨厉害", "R2", "网络口语"),
    (r"(?<![一-鿿])挺(?:.{0,2})", "R2", "口语弱化副词"),
    (r"一堆|一大堆|好多|老多", "R2", "口语模糊量词"),
    (r"搞[一了个]|弄[一了个]|整[一了个]", "R2", "口语动词"),
    (r"这玩意儿?|那玩意儿?|这东西|那东西", "R2", "口语指代"),
    (r"这块|那块|这边|那边", "R2", "口语方位"),
    (r"对吧[?？]|是吧[?？]|不是吗[?？]|对不对[?？]", "R3", "口语反问"),
    (r"说白了|长话短说|总之吧", "R2", "口语连接"),
    (r"哈哈|嘿嘿|呵呵", "R4", "语气词"),
    (r"yyds|绝绝子|真香|破防|上头", "R4", "网络流行语"),
    (r"！！|？？|～", "R4", "多重标点/波浪号"),
    (r"好像.{0,8}(表明|显示|证明|说明)", "R5", "结论中模糊副词"),
    (r"似乎.{0,8}(表明|显示|证明|说明)", "R5", "结论中模糊副词"),
    (r"大概.{0,5}\d", "R5", "数字前模糊副词"),
    (r"估计是", "R5", "口语推测"),
]


# ---------- 口语/书面语度词表（v2.3 新增）----------
# 与 REGISTER_REDLINES 分离：红线 = 硬违规（gate 判据），本表 = 连续扣分（W 判据）。
# 类别: verb=口语动词短语, lecture=讲解体句式, casual-syntax=口语句法, symbol=非规范符号
# 描述里的 "→" 给出书面语替换方向，详表见 references/formal-register-guide.md
COLLOQUIAL_PATTERNS: list[tuple[str, str, str]] = [
    # ---- verb：口语动词/短语（两份实测样本 + 常见博客体）----
    (r"(?:一直|还|都|总)在[涨跌]", "verb", "口语涨跌 → 持续增长/下降"),
    (r"高出一截|差一截|矮一截|高一大截", "verb", "口语比较 → 显著高于/明显不足"),
    (r"跟不上|赶不上|追不上", "verb", "口语能力否定 → 难以匹配/无法满足"),
    (r"压低", "verb", "口语增减 → 降低"),
    (r"挡在|挡住|拦住", "verb", "口语阻拦 → 拦截/阻止"),
    (r"绕开", "verb", "口语规避 → 规避/避免"),
    (r"牵出|扯出", "verb", "口语引出 → 引发/导致"),
    (r"顺手|随手", "verb", "口语便利 → 便捷"),
    (r"帮了.{0,3}忙|帮.{0,2}大忙", "verb", "口语帮助 → 显著降低了…成本"),
    (r"点进去|点开", "verb", "口语交互 → 进入/打开"),
    (r"翻来翻去|来回翻|翻了半天", "verb", "口语查找 → 逐一检索"),
    (r"再造一套|另搞一套", "verb", "口语重复建设 → 重复建设"),
    (r"那一套|这一套(?!.{0,3}(?:理论|方法|体系))", "verb", "口语指代 → 该类模式"),
    (r"落到[^，。；,]{0,6}上来?(?![游])", "verb", "口语落实 → 具体到…层面"),
    (r"派上用场", "verb", "口语效用 → 得以应用"),
    (r"跑通|跑起来|跑不动", "verb", "口语运行 → 完整运行/无法运行"),
    (r"卡在|卡住|卡壳", "verb", "口语阻塞 → 受阻于/停滞"),
    (r"砍掉|砍去", "verb", "口语删减 → 删除/裁剪"),
    (r"塞进|塞到|塞入", "verb", "口语放置 → 纳入/置入"),
    (r"摸清|摸透|摸底", "verb", "口语了解 → 明确/掌握"),
    (r"[写用找]起来", "verb", "口语体验 → 在…过程中"),
    (r"搞定|弄好了|整好了", "verb", "口语完成 → 完成"),
    (r"踩坑|踩了.{0,2}坑", "verb", "口语受挫 → 遇到问题"),
    # ---- lecture：讲解体/博客体句式 ----
    (r"是这样的[：:，,]", "lecture", "讲解体开场 → 处理流程如下："),
    (r"来看一下|来讲一下|来说一下|再看看", "lecture", "讲解体引导 → 删除或改陈述句"),
    (r"说回|话说回来", "lecture", "讲解体话题切换 → 删除"),
    (r"顺便提一下|插一句", "lecture", "讲解体插话 → 删除"),
    (r"举个例子|打个比方|比方说", "lecture", "讲解体举例 → 例如"),
    (r"也就是说|换句话说", "lecture", "讲解体复述 → 即/亦即"),
    # ---- casual-syntax：口语句法 ----
    (r"要是.{0,20}的话", "casual-syntax", "口语条件句 → 若…则"),
    (r"[^。；;，,]{2,10}的话(?![语题])[，,]", "casual-syntax", "口语假设助词 → 若"),
    (r"[吧呢嘛啦哦][。，,！!]", "casual-syntax", "句末语气助词 → 删除"),
    (r"没法(?![律])", "casual-syntax", "口语否定 → 无法"),
    (r"不然[，,]", "casual-syntax", "口语转折 → 否则"),
    # ---- symbol：非规范符号（大陆学术规范）----
    (r"[「」『』]", "symbol", "直角引号 → 中文双引号“”"),
    (r"→", "symbol", "正文箭头 → 文字表述或规范流程图"),
    (r"[～〜]", "symbol", "波浪号 → 至/-"),
]

# W 计算常量（v2.3）
FORMALITY_FULL_PENALTY_PER_KCHAR = 5.0   # 每千字命中 5 处口语 → W = 0
FORMALITY_CHAR_FLOOR = 300               # 短段落密度平滑下限（字）
W_GATE_THRESHOLD = 0.6                   # W 低于此值视同 Register Gate FAIL


# ---------- 数据类 ----------
@dataclass
class FingerprintHit:
    text: str
    pattern: str
    significance: str
    category: str
    span: tuple[int, int]


@dataclass
class RegisterViolation:
    rule: str
    text: str
    description: str
    span: tuple[int, int]


@dataclass
class ColloquialHit:
    text: str
    category: str
    description: str
    span: tuple[int, int]


@dataclass
class EvidenceCounts:
    numbers: int = 0
    citations: int = 0
    methodology: int = 0
    boundaries: int = 0
    cn_terms: int = 0
    critical_perspective: int = 0  # v2.2 新增：批判性视角（"内生性""样本限制"等）

    @property
    def total(self) -> int:
        return (self.numbers + self.citations + self.methodology +
                self.boundaries + self.cn_terms + self.critical_perspective)


@dataclass
class ParagraphReport:
    para_id: str
    text_length: int
    sentence_lengths: list[int]
    burstiness_sigma2: float
    burstiness_ratio: float
    fingerprint_score: float
    fingerprint_score_weighted: float  # v2.2: 按章节加权
    fingerprint_hits: list[FingerprintHit] = field(default_factory=list)
    abstract_suffix_overuse: bool = False
    register_violations: list[RegisterViolation] = field(default_factory=list)
    evidence: EvidenceCounts = field(default_factory=EvidenceCounts)
    risk: str = "low"
    recommended_axes: list[str] = field(default_factory=list)
    section: str = "default"
    section_weight: float = 1.0
    citation_penalty: bool = False  # v2.2: 综述类缺引用
    colloquial_hits: list[ColloquialHit] = field(default_factory=list)  # v2.3
    formality: float = 1.0                                              # v2.3: 书面语度 W


# ---------- 文本处理 ----------
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")
CN_CHAR_RE = re.compile(r"[一-鿿]")

# Evidence 模式
NUMBER_PATTERNS = [
    re.compile(r"\d+\.?\d*\s*%"),
    re.compile(r"\d+\.\d+"),
    re.compile(r"\bp\s*[<>=]\s*0?\.\d+", re.IGNORECASE),
    re.compile(r"95%\s*CI"),
    re.compile(r"\bN\s*=\s*\d+"),
    re.compile(r"\bn\s*=\s*\d+"),
    re.compile(r"β\s*=\s*-?\d+\.?\d*"),       # v2.2: β 系数
    re.compile(r"α\s*=\s*0?\.\d+"),            # v2.2: α 显著性
    re.compile(r"\d{4}\s*年"),
    re.compile(r"(?:19|20)\d{2}"),
    re.compile(r"第\s*\d+\s*(章|节|条)"),
]
CITATION_PATTERN = re.compile(r"[一-鿿A-Za-z]+\s*(等)?\s*[\(（]\s*(?:19|20)\d{2}[\)）]")
METHODOLOGY_KEYWORDS = [
    "交叉验证", "学习率", "batch size", "epoch", "macro-F1", "micro-F1",
    "Adam", "SGD", "随机种子", "cosine", "warmup", "正则化", "dropout",
    "t检验", "t 检验", "ANOVA", "方差分析", "Cronbach", "Likert",
    "Bonferroni", "Cohen", "Shapiro", "p<", "p <",
    "QPS", "P95", "P99", "延迟", "吞吐",
]
BOUNDARY_RE = re.compile(
    "局限|受限于|失效|不成立|假设依赖|"
    "仅适用于|超出该|前提是|前提一旦|反例|"
    "在.{0,8}条件下成立|样本量.{0,3}<|样本量.{0,3}>|"
    r"n\s*<\s*\d+|n\s*>\s*\d+"
)
CN_DOMAIN_TERMS = [
    "收敛", "鲁棒性", "偏倚", "效应量", "Pareto", "帕累托", "纳什均衡",
    "信道容量", "互信息", "稀疏性", "凸性", "上界", "下界", "渐近",
    "异方差", "多重共线", "倾向得分",
    "信效度", "中介效应", "调节效应", "扎根理论",
]
# v2.2 新增：批判性视角词（实测显示文献综述加这些能从 65% → 35%）
CRITICAL_PERSPECTIVE_TERMS = [
    "内生性", "外生性", "样本限制", "样本偏差", "选择性偏差", "幸存者偏差",
    "因果推断", "反事实", "工具变量", "自然实验", "断点回归",
    "稳健性", "异质性", "敏感性分析", "替代解释", "竞争性假设",
    "生态效度", "外部效度", "内部效度",
]


def split_sentences(text: str) -> list[str]:
    raw = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return [s for s in raw if len(s) >= 3]


def cn_char_count(text: str) -> int:
    return len(CN_CHAR_RE.findall(text))


def sentence_length(s: str, use_jieba: bool = False) -> int:
    """句子长度。默认字符级近似；--with-jieba 时改词级。"""
    if use_jieba and _JIEBA is not None:
        # 词级分词（更接近真实"词数"）
        words = [w for w in _JIEBA.cut(s) if w.strip()]
        return len(words)
    cn = cn_char_count(s)
    en_words = len(re.findall(r"[A-Za-z]+", s))
    nums = len(re.findall(r"\d+\.?\d*", s))
    return cn + en_words + nums


def variance(xs: list[int]) -> float:
    if not xs:
        return 0.0
    mu = sum(xs) / len(xs)
    return sum((x - mu) ** 2 for x in xs) / len(xs)


def deduplicate_overlapping_hits(hits: list[FingerprintHit]) -> list[FingerprintHit]:
    """v2.2 修复：去除完全重叠的命中（同一文本被多个正则匹配只算一次，保留显著度最高的）。"""
    if not hits:
        return hits
    # 按 (start, end) 分组，每组保留权重最高的
    groups: dict[tuple[int, int], FingerprintHit] = {}
    for h in hits:
        if h.span == (0, 0):
            # 抽象后缀堆砌虚拟跨度，单独保留
            continue
        key = h.span
        existing = groups.get(key)
        if existing is None or SIGNIFICANCE_WEIGHT[h.significance] > SIGNIFICANCE_WEIGHT[existing.significance]:
            groups[key] = h
    # 进一步：完全包含关系也去重（短跨度若被长跨度覆盖且权重 ≤ 长跨度，删除短跨度）
    spans = sorted(groups.values(), key=lambda x: (x.span[0], -(x.span[1] - x.span[0])))
    result = []
    occupied: list[tuple[int, int]] = []
    for h in spans:
        s, e = h.span
        # 是否被已接受跨度完全覆盖
        if any(os <= s and oe >= e for os, oe in occupied):
            continue
        result.append(h)
        occupied.append((s, e))
    # 把抽象后缀堆砌的虚拟命中加回
    suffix_hits = [h for h in hits if h.span == (0, 0)]
    return result + suffix_hits


# ---------- 指纹扫描 ----------
def scan_fingerprints(text: str) -> tuple[list[FingerprintHit], bool]:
    raw_hits: list[FingerprintHit] = []
    for pattern, sig, cat in FINGERPRINTS:
        for m in re.finditer(pattern, text):
            raw_hits.append(FingerprintHit(
                text=m.group(0),
                pattern=pattern,
                significance=sig,
                category=cat,
                span=(m.start(), m.end()),
            ))

    # v2.2: 去重叠
    hits = deduplicate_overlapping_hits(raw_hits)

    # 抽象后缀堆砌检测
    suffix_overuse = False
    hua_count = sum(text.count(w) for w in ABSTRACT_SUFFIX_HUA)
    xing_count = sum(text.count(w) for w in ABSTRACT_SUFFIX_XING)
    for total, suffix_name in [(hua_count, "化"), (xing_count, "性")]:
        if total >= 2:
            suffix_overuse = True
            hits.append(FingerprintHit(
                text=f"{suffix_name}-后缀堆砌×{total}",
                pattern=f"abstract_suffix_{suffix_name}",
                significance="B",
                category="抽象后缀",
                span=(0, 0),
            ))

    return hits, suffix_overuse


def fingerprint_score(hits: list[FingerprintHit]) -> float:
    return round(sum(SIGNIFICANCE_WEIGHT.get(h.significance, 0.5) for h in hits), 2)


# ---------- Register 扫描 ----------
def scan_register(text: str) -> list[RegisterViolation]:
    violations: list[RegisterViolation] = []
    for pattern, rule, desc in REGISTER_REDLINES:
        for m in re.finditer(pattern, text):
            violations.append(RegisterViolation(
                rule=rule,
                text=m.group(0),
                description=desc,
                span=(m.start(), m.end()),
            ))
    return violations


# ---------- 口语扫描与书面语度（v2.3）----------
def scan_colloquial(text: str) -> list[ColloquialHit]:
    hits: list[ColloquialHit] = []
    for pattern, category, desc in COLLOQUIAL_PATTERNS:
        for m in re.finditer(pattern, text):
            hits.append(ColloquialHit(
                text=m.group(0), category=category,
                description=desc, span=(m.start(), m.end()),
            ))
    return hits


def formality_score(text: str, hits: list[ColloquialHit] | None = None) -> float:
    """书面语度 W ∈ [0,1]。状态量：只看当前文本，不比较改前改后。

    W = clamp(1 - 每千字口语命中数 / FORMALITY_FULL_PENALTY_PER_KCHAR, 0, 1)
    短段落用 FORMALITY_CHAR_FLOOR 平滑，避免一处命中直接归零。
    """
    if hits is None:
        hits = scan_colloquial(text)
    chars = max(cn_char_count(text), FORMALITY_CHAR_FLOOR)
    per_kchar = len(hits) / chars * 1000
    return round(max(0.0, min(1.0, 1 - per_kchar / FORMALITY_FULL_PENALTY_PER_KCHAR)), 3)


# ---------- Evidence 扫描 ----------
def scan_evidence(text: str) -> EvidenceCounts:
    ev = EvidenceCounts()
    for pat in NUMBER_PATTERNS:
        ev.numbers += len(pat.findall(text))
    ev.citations = len(CITATION_PATTERN.findall(text))
    ev.methodology = sum(text.count(kw) for kw in METHODOLOGY_KEYWORDS)
    ev.boundaries = len(BOUNDARY_RE.findall(text))
    ev.cn_terms = sum(text.count(kw) for kw in CN_DOMAIN_TERMS)
    ev.critical_perspective = sum(text.count(kw) for kw in CRITICAL_PERSPECTIVE_TERMS)
    return ev


# ---------- 段落分析 ----------
def analyze_paragraph(
    text: str,
    para_id: str = "§1",
    section: str = "default",
    use_jieba: bool = False,
) -> ParagraphReport:
    sents = split_sentences(text)
    lengths = [sentence_length(s, use_jieba=use_jieba) for s in sents]
    sigma2 = variance(lengths) if lengths else 0.0
    ratio = max(lengths) / max(min(lengths), 1) if lengths else 0.0

    hits, suffix_overuse = scan_fingerprints(text)
    fp_score = fingerprint_score(hits)

    # v2.2: 章节加权
    weight = SECTION_WEIGHTS.get(section.lower(), 1.0)
    fp_score_weighted = round(fp_score * weight, 2)

    register = scan_register(text)
    colloquial = scan_colloquial(text)
    formality = formality_score(text, colloquial)
    evidence = scan_evidence(text)
    text_len = sentence_length(text, use_jieba=use_jieba)
    evidence_density = (evidence.total / max(text_len, 1)) * 1000

    # v2.2: 综述类缺引用惩罚（实测 +10-15% AIGC 率，linggantext 2026 攻略）
    citation_penalty = (
        section.lower() in {"literature_review", "intro", "introduction", "background"}
        and evidence.citations == 0
        and text_len >= 30
    )

    # 风险判定（用加权后的指纹分）
    risk = "low"
    axes: list[str] = []
    if fp_score_weighted >= 5 or sigma2 < 50 or evidence_density < 1 or citation_penalty:
        risk = "high"
    elif fp_score_weighted >= 2 or sigma2 < 150 or evidence_density < 3:
        risk = "mid"

    if fp_score >= 2:
        axes.append("A")
    if sigma2 < 150 or ratio < 3:
        axes.append("B")
    if evidence_density < 3 or citation_penalty:
        axes.append("C")

    return ParagraphReport(
        para_id=para_id,
        text_length=text_len,
        sentence_lengths=lengths,
        burstiness_sigma2=round(sigma2, 1),
        burstiness_ratio=round(ratio, 2),
        fingerprint_score=fp_score,
        fingerprint_score_weighted=fp_score_weighted,
        fingerprint_hits=hits,
        abstract_suffix_overuse=suffix_overuse,
        register_violations=register,
        evidence=evidence,
        risk=risk,
        recommended_axes=axes,
        section=section,
        section_weight=weight,
        citation_penalty=citation_penalty,
        colloquial_hits=colloquial,
        formality=formality,
    )


# ---------- 5 维奖励：改前 vs 改后 ----------
def compute_reward(before_text: str, after_text: str, section: str = "default",
                   use_jieba: bool = False) -> dict:
    before = analyze_paragraph(before_text, "before", section, use_jieba)
    after = analyze_paragraph(after_text, "after", section, use_jieba)

    # F: 用加权指纹分计算（高权重区段更难拿满分）
    F = max(0.0, 1 - after.fingerprint_score_weighted / max(before.fingerprint_score_weighted, 0.5))
    F = round(min(F, 1.0), 3)

    # B: 句长方差提升
    B_raw = (after.burstiness_sigma2 - before.burstiness_sigma2) / 200
    B = max(0.0, min(B_raw, 1.0))
    if after.burstiness_sigma2 > 600:
        B *= 0.5
    if after.sentence_lengths:
        mn, mx = min(after.sentence_lengths), max(after.sentence_lengths)
        if mn >= 15 or mx <= 50:
            B = max(0.0, B - 0.3)
    B = round(B, 3)

    # E: 痕迹增量
    delta_evidence = after.evidence.total - before.evidence.total
    E = round(max(0.0, min(delta_evidence / 5, 1.0)), 3)

    # Gates
    W = after.formality
    formality_pass = W >= W_GATE_THRESHOLD          # v2.3 双保险
    register_pass = len(after.register_violations) == 0
    char_ratio = after.text_length / max(before.text_length, 1)
    integrity_pass = char_ratio >= 0.7
    citation_pass = not after.citation_penalty  # v2.2: 综述类必须保留至少一处引用

    if not (register_pass and integrity_pass and citation_pass and formality_pass):
        R = 0.0
    else:
        dQ_default = 0.5
        R = round(0.25 * F + 0.20 * B + 0.20 * E + 0.15 * dQ_default + 0.20 * W, 3)

    return {
        "section": section,
        "section_weight": SECTION_WEIGHTS.get(section.lower(), 1.0),
        "before": _report_to_dict(before),
        "after": _report_to_dict(after),
        "scores": {
            "F": F, "B": B, "E": E,
            "W": W,
            "dQ_placeholder": 0.5,
            "R_with_default_dQ": R,
        },
        "gates": {
            "register": "PASS" if register_pass else "FAIL",
            "formality": "PASS" if formality_pass else "FAIL",
            "integrity_simple": "PASS" if integrity_pass else "FAIL",
            "citation_in_review_section": "PASS" if citation_pass else "FAIL",
        },
        "deltas": {
            "fingerprint_raw": before.fingerprint_score - after.fingerprint_score,
            "fingerprint_weighted": before.fingerprint_score_weighted - after.fingerprint_score_weighted,
            "sigma2": after.burstiness_sigma2 - before.burstiness_sigma2,
            "evidence": delta_evidence,
            "formality": round(after.formality - before.formality, 3),
            "char_ratio": round(char_ratio, 2),
        },
    }


def _report_to_dict(r: ParagraphReport) -> dict:
    return asdict(r)


# ---------- 文档级 ----------
SECTION_HEURISTICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^#{1,3}\s*(摘\s*要|abstract)", re.IGNORECASE | re.MULTILINE), "abstract"),
    (re.compile(r"^#{1,3}\s*(引\s*言|绪\s*论|introduction|引论)", re.IGNORECASE | re.MULTILINE), "intro"),
    (re.compile(r"^#{1,3}\s*(结\s*论|总\s*结|conclusion)", re.IGNORECASE | re.MULTILINE), "conclusion"),
    (re.compile(r"^#{1,3}\s*(创新点|主要贡献|本文贡献|innovation|contribution)", re.IGNORECASE | re.MULTILINE), "innovation"),
    (re.compile(r"^#{1,3}\s*(文献综述|相关工作|literature\s*review)", re.IGNORECASE | re.MULTILINE), "literature_review"),
    (re.compile(r"^#{1,3}\s*(方法|模型|method|methodology)", re.IGNORECASE | re.MULTILINE), "method"),
    (re.compile(r"^#{1,3}\s*(实验|experiment)", re.IGNORECASE | re.MULTILINE), "experiment"),
    (re.compile(r"^#{1,3}\s*(结果|result)", re.IGNORECASE | re.MULTILINE), "results"),
    (re.compile(r"^#{1,3}\s*(讨论|discussion)", re.IGNORECASE | re.MULTILINE), "discussion"),
    (re.compile(r"^#{1,3}\s*(背景|background)", re.IGNORECASE | re.MULTILINE), "background"),
    (re.compile(r"^#{1,3}\s*(理论基础|theory)", re.IGNORECASE | re.MULTILINE), "theory"),
    (re.compile(r"^#{1,3}\s*(致\s*谢|acknowledgment)", re.IGNORECASE | re.MULTILINE), "ack"),
]


def detect_section(text_before_para: str) -> str:
    """v2.2: 根据段落前最近的 markdown 标题猜章节类型。"""
    last_heading = None
    last_section = "default"
    for pat, sect in SECTION_HEURISTICS:
        for m in pat.finditer(text_before_para):
            if last_heading is None or m.start() > last_heading:
                last_heading = m.start()
                last_section = sect
    return last_section


def split_paragraphs(text: str) -> list[tuple[str, str, str]]:
    """v2.2: 切段同时返回章节类型 [(id, paragraph_text, section)]"""
    raw = re.split(r"\n\s*\n", text)
    paras = []
    cursor = 0
    para_idx = 0
    for chunk in raw:
        if chunk.strip() and not chunk.strip().startswith("#"):
            section = detect_section(text[:cursor + len(chunk)])
            para_idx += 1
            paras.append((f"§{para_idx}", chunk.strip(), section))
        cursor += len(chunk) + 2  # +2 for the split delimiter
    return paras


def analyze_document(text: str, use_jieba: bool = False) -> dict:
    paras = split_paragraphs(text)
    reports = [analyze_paragraph(t, pid, sect, use_jieba) for pid, t, sect in paras]
    high = sum(1 for r in reports if r.risk == "high")
    mid = sum(1 for r in reports if r.risk == "mid")
    low = sum(1 for r in reports if r.risk == "low")

    total_chars = sum(r.text_length for r in reports)
    total_fp = round(sum(r.fingerprint_score for r in reports), 2)
    total_fp_weighted = round(sum(r.fingerprint_score_weighted for r in reports), 2)
    total_evidence = sum(r.evidence.total for r in reports)
    avg_sigma2 = round(sum(r.burstiness_sigma2 for r in reports) / max(len(reports), 1), 1)

    section_breakdown: dict[str, int] = {}
    for r in reports:
        section_breakdown[r.section] = section_breakdown.get(r.section, 0) + 1

    return {
        "summary": {
            "total_paragraphs": len(reports),
            "high_risk": high,
            "mid_risk": mid,
            "low_risk": low,
            "total_chars": total_chars,
            "total_fingerprint_score": total_fp,
            "total_fingerprint_weighted": total_fp_weighted,
            "fingerprint_per_1k_chars": round(total_fp / max(total_chars, 1) * 1000, 2),
            "fingerprint_weighted_per_1k": round(total_fp_weighted / max(total_chars, 1) * 1000, 2),
            "avg_burstiness_sigma2": avg_sigma2,
            "total_evidence": total_evidence,
            "evidence_per_1k_chars": round(total_evidence / max(total_chars, 1) * 1000, 2),
            "section_breakdown": section_breakdown,
            "jieba_enabled": use_jieba and _JIEBA is not None,
        },
        "paragraphs": [_report_to_dict(r) for r in reports],
    }


# ---------- v2.3: 段落级 / 文档级高级特征 ----------
PRONOUN_PATTERNS = {
    "本研究": re.compile(r"本研究"),
    "本文": re.compile(r"本文"),
    "本章": re.compile(r"本章"),
    "本节": re.compile(r"本节"),
    "笔者": re.compile(r"笔者"),
    "我们": re.compile(r"我们"),
    "我": re.compile(r"(?<![一-鿿一-龯])我(?![一-鿿一-龯们])"),
}

# 标点节奏指纹（基于 GPTZero 等检测器观察）
# AI 偏好顿号（爱列举）、罕用分号、几乎不用破折号；真人相反
PUNCT_DUNHAO = "、"
PUNCT_FENHAO = "；;"
PUNCT_DASH = "——"
PUNCT_QUOTE = "「」『』""''"


def punctuation_rhythm(text: str) -> dict:
    """计算标点密度（每千字）。"""
    chars = max(cn_char_count(text), 1)
    return {
        "dunhao_per_1k": round(text.count(PUNCT_DUNHAO) / chars * 1000, 2),
        "fenhao_per_1k": round(sum(text.count(p) for p in PUNCT_FENHAO) / chars * 1000, 2),
        "dash_per_1k": round(text.count(PUNCT_DASH) / chars * 1000, 2),
        "quote_per_1k": round(sum(text.count(p) for p in PUNCT_QUOTE) / chars * 1000, 2),
    }


def punctuation_signal(rhythm: dict) -> tuple[float, list[str]]:
    """根据标点密度返回 AI 信号强度（0-1）和具体警告。"""
    warnings = []
    score = 0.0
    # 顿号过密 (> 8/千字 是 AI 偏好列举)
    if rhythm["dunhao_per_1k"] > 8:
        score += 0.3
        warnings.append(f"顿号过密 ({rhythm['dunhao_per_1k']}/千字) — AI 爱列举")
    # 分号几乎不用 (< 0.5/千字)
    if rhythm["fenhao_per_1k"] < 0.5:
        score += 0.2
        warnings.append(f"分号缺席 ({rhythm['fenhao_per_1k']}/千字) — 真人学术常用分号")
    # 破折号几乎不用 (< 0.3/千字)
    if rhythm["dash_per_1k"] < 0.3:
        score += 0.2
        warnings.append(f"破折号缺席 ({rhythm['dash_per_1k']}/千字)")
    return min(score, 1.0), warnings


def paragraph_structure_fingerprint(paragraph_text: str) -> str:
    """提取段落"主旨+三支撑+总结"指纹：取段首句和段尾句各前 10 字。"""
    sents = split_sentences(paragraph_text)
    if len(sents) < 3:
        return ""
    head = sents[0][:10]
    tail = sents[-1][:10]
    return f"{head}|{tail}"


def detect_structural_homogeneity(paragraphs: list[str]) -> dict:
    """检测多段是否使用相同的"段首论断 + 段尾回扣"结构。"""
    fingerprints = []
    for p in paragraphs:
        fp = paragraph_structure_fingerprint(p)
        if fp:
            fingerprints.append(fp)
    if len(fingerprints) < 2:
        return {"homogeneous_pairs": 0, "structure_homogeneity_score": 0.0}

    # 计算段落对的"开头主谓相似度"+"结尾主谓相似度"
    homogeneous_pairs = 0
    for i in range(len(fingerprints)):
        for j in range(i + 1, len(fingerprints)):
            head_i, tail_i = fingerprints[i].split("|")
            head_j, tail_j = fingerprints[j].split("|")
            # 简化：开头前 3 字 / 结尾前 3 字 重合 → 同质（"本研究" / "综上所" 等 3 字短语已经是强信号）
            if (len(head_i) >= 3 and len(head_j) >= 3 and head_i[:3] == head_j[:3]) or \
               (len(tail_i) >= 3 and len(tail_j) >= 3 and tail_i[:3] == tail_j[:3]):
                homogeneous_pairs += 1

    total_pairs = len(fingerprints) * (len(fingerprints) - 1) / 2
    score = homogeneous_pairs / max(total_pairs, 1)
    return {
        "homogeneous_pairs": homogeneous_pairs,
        "total_pairs": int(total_pairs),
        "structure_homogeneity_score": round(score, 2),
    }


def detect_pronoun_inconsistency(paragraphs: list[str]) -> dict:
    """检测人称用法不一致（维普"拼接预警"信号）。"""
    counts = {name: 0 for name in PRONOUN_PATTERNS}
    for p in paragraphs:
        for name, pat in PRONOUN_PATTERNS.items():
            counts[name] += len(pat.findall(p))
    total = sum(counts.values())
    if total == 0:
        return {"distribution": counts, "diversity": 0.0, "warning": None}

    # 计算"分布的香农熵 / 最大熵"作为多样性。多样性过高（混用太多种）= 拼接信号
    import math
    proportions = [c / total for c in counts.values() if c > 0]
    entropy = -sum(p * math.log2(p) for p in proportions if p > 0)
    max_entropy = math.log2(len([p for p in proportions if p > 0])) if len(proportions) > 1 else 1
    diversity = entropy / max(max_entropy, 0.01)

    warning = None
    used_count = sum(1 for c in counts.values() if c > 0)
    if used_count >= 4:
        warning = f"人称变体使用 {used_count} 种（{[k for k,v in counts.items() if v>0]}），可能触发维普拼接预警"
    elif counts["我们"] > 0 and counts["本研究"] > 0 and counts["我们"] >= counts["本研究"] / 2:
        warning = "「我们」与「本研究」混用，体裁不统一"

    return {
        "distribution": counts,
        "diversity": round(diversity, 3),
        "used_variants": used_count,
        "warning": warning,
    }


def detect_inter_paragraph_consistency(reports: list) -> dict:
    """检测相邻段落 σ² 跳变（维普关注的"句子平均长度波动"）。"""
    if len(reports) < 2:
        return {"max_sigma2_jump": 0, "warning": None}
    sigma2_seq = [r.burstiness_sigma2 for r in reports]
    jumps = []
    for i in range(1, len(sigma2_seq)):
        jump = abs(sigma2_seq[i] - sigma2_seq[i - 1])
        jumps.append((i, jump))
    max_jump = max(j for _, j in jumps)
    warning = None
    if max_jump > 300:
        worst_pair = max(jumps, key=lambda x: x[1])
        warning = f"§{worst_pair[0]} 与上一段 σ² 跳变 {worst_pair[1]:.0f}（>300 阈值）— 可能被维普标为拼接"
    return {
        "max_sigma2_jump": round(max_jump, 1),
        "sigma2_sequence": [round(s, 1) for s in sigma2_seq],
        "warning": warning,
    }


def analyze_document_advanced(text: str, use_jieba: bool = False) -> dict:
    """v2.3: 文档级高级分析（段间一致性、结构同质化、标点节奏、人称混用）。"""
    paras = split_paragraphs(text)
    paragraph_texts = [t for _, t, _ in paras]
    reports = [analyze_paragraph(t, pid, sect, use_jieba) for pid, t, sect in paras]

    base = analyze_document(text, use_jieba)

    structural = detect_structural_homogeneity(paragraph_texts)
    pronoun = detect_pronoun_inconsistency(paragraph_texts)
    inter_para = detect_inter_paragraph_consistency(reports)

    rhythm = punctuation_rhythm(text)
    punct_score, punct_warnings = punctuation_signal(rhythm)

    # 综合 AI 风险增量（在原有 fingerprint_weighted 之外的"段落级 AI 信号"）
    advanced_risk = 0.0
    advanced_warnings = []
    if structural["structure_homogeneity_score"] > 0.3:
        advanced_risk += 0.3
        advanced_warnings.append(
            f"段落结构同质化 ({structural['structure_homogeneity_score']:.0%})"
            f"—{structural['homogeneous_pairs']} 对段落开头/结尾雷同"
        )
    if pronoun["warning"]:
        advanced_risk += 0.2
        advanced_warnings.append(pronoun["warning"])
    if inter_para["warning"]:
        advanced_risk += 0.2
        advanced_warnings.append(inter_para["warning"])
    advanced_risk += punct_score * 0.3
    advanced_warnings.extend(punct_warnings)

    base["advanced"] = {
        "structural_homogeneity": structural,
        "pronoun_consistency": pronoun,
        "inter_paragraph": inter_para,
        "punctuation_rhythm": rhythm,
        "punctuation_signal_score": round(punct_score, 2),
        "advanced_risk_score": round(min(advanced_risk, 1.0), 2),
        "advanced_warnings": advanced_warnings,
    }
    return base


# ---------- CLI ----------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="paper-humanize v2.2 量化打分脚本")
    p.add_argument("--mode", choices=["diagnose", "diagnose-doc", "compare", "lint",
                                      "advanced-doc", "register"],
                   required=True)
    p.add_argument("--file", type=Path, help="单文件输入")
    p.add_argument("--before", type=Path)
    p.add_argument("--after", type=Path)
    p.add_argument("--text", type=str, help="直接传入文本")
    p.add_argument("--section", default="default",
                   choices=list(SECTION_WEIGHTS.keys()),
                   help="章节类型，影响指纹加权（v2.2）")
    p.add_argument("--with-jieba", action="store_true",
                   help="启用 jieba 词级分词（需 pip install jieba）")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args(argv)

    indent = 2 if args.pretty else None

    if args.with_jieba and _JIEBA is None:
        print(json.dumps({"warning": "--with-jieba specified but jieba not installed; falling back to char-level"}),
              file=sys.stderr)

    if args.mode == "diagnose":
        text = args.text or sys.stdin.read()
        report = analyze_paragraph(text.strip(), "input", args.section, args.with_jieba)
        print(json.dumps(_report_to_dict(report), ensure_ascii=False, indent=indent))
        return 0

    if args.mode == "diagnose-doc":
        if not args.file:
            print(json.dumps({"error": "--file required"}), file=sys.stderr)
            return 2
        text = args.file.read_text(encoding="utf-8")
        result = analyze_document(text, args.with_jieba)
        print(json.dumps(result, ensure_ascii=False, indent=indent))
        return 0

    if args.mode == "compare":
        if not (args.before and args.after):
            print(json.dumps({"error": "--before and --after required"}), file=sys.stderr)
            return 2
        before = args.before.read_text(encoding="utf-8")
        after = args.after.read_text(encoding="utf-8")
        result = compute_reward(before, after, args.section, args.with_jieba)
        print(json.dumps(result, ensure_ascii=False, indent=indent))
        return 0

    if args.mode == "advanced-doc":
        if not args.file:
            print(json.dumps({"error": "--file required"}), file=sys.stderr)
            return 2
        text = args.file.read_text(encoding="utf-8")
        result = analyze_document_advanced(text, args.with_jieba)
        print(json.dumps(result, ensure_ascii=False, indent=indent))
        return 0

    if args.mode == "register":
        if args.text:
            text = args.text
        elif args.file:
            text = args.file.read_text(encoding="utf-8")
        else:
            text = sys.stdin.read()
        hits = scan_colloquial(text)
        violations = scan_register(text)
        W = formality_score(text, hits)
        print(json.dumps({
            "formality_W": W,
            "w_gate": "PASS" if W >= W_GATE_THRESHOLD else "FAIL",
            "hits_per_kchar": round(len(hits) / max(cn_char_count(text), 1) * 1000, 2),
            "colloquial_hits": [asdict(h) for h in hits],
            "register_violations": [asdict(v) for v in violations],
        }, ensure_ascii=False, indent=indent))
        return 0

    if args.mode == "lint":
        if not args.file:
            print(json.dumps({"error": "--file required"}), file=sys.stderr)
            return 2
        text = args.file.read_text(encoding="utf-8")
        paras = split_paragraphs(text)
        lints = []
        for pid, t, sect in paras:
            hits, _ = scan_fingerprints(t)
            register = scan_register(t)
            if hits or register:
                lints.append({
                    "para_id": pid,
                    "section": sect,
                    "preview": t[:50] + ("..." if len(t) > 50 else ""),
                    "fingerprints": [asdict(h) for h in hits],
                    "register_violations": [asdict(v) for v in register],
                })
        print(json.dumps({"lints": lints, "total": len(lints)},
                         ensure_ascii=False, indent=indent))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
