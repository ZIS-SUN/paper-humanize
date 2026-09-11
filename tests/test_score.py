#!/usr/bin/env python3
"""
paper-humanize 测试套件 (v2.3)

零依赖（仅 unittest）。跑：
  python3 tests/test_score.py
或通过 cli:
  python3 scripts/cli.py test
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 让测试能 import scripts/score.py
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import score  # noqa: E402


# ---------- 已知样本 ----------
HEAVY_AI = """随着人工智能技术的快速发展，深度学习在图像识别领域得到了广泛应用。\
本文针对当前图像分类任务中存在的若干问题，提出了一种新的卷积神经网络模型。\
该模型通过引入注意力机制，有效地提升了分类性能。\
综上所述，所提出的方法具有重要的研究意义和应用价值。"""

CLEAN_HUMAN = """卷积神经网络在 ImageNet 上趋于饱和，但在细粒度场景下仍受限于类间差异微弱。\
本文在 ResNet-50 主干上引入通道-空间双路注意力。\
在 CUB-200 三个数据集上 Top-1 准确率为 87.4%、93.1% 和 91.6%。\
提升在 n ≥ 30 时稳定；样本更稀疏时方差扩大。"""

# v2.3: 真实口水化样本（取自用户提供的两份实际产物）
WATERY_SAMPLE = """新能源汽车保有量这几年一直在涨，期望比早几年高出一截，\
线下渠道却始终跟不上节奏。整个流程是这样的：点击「删除」按钮后，\
把误触挡在请求发出前，后端绕开物理删除，顺手也便于审计，\
数据库操作写起来帮了不少忙。"""


class TestSentenceUtils(unittest.TestCase):
    def test_split_sentences_basic(self):
        sents = score.split_sentences("第一句。第二句！第三句？")
        self.assertEqual(len(sents), 3)

    def test_split_sentences_filters_short(self):
        sents = score.split_sentences("正常一句。短。")
        self.assertEqual(len(sents), 1)

    def test_cn_char_count(self):
        self.assertEqual(score.cn_char_count("hello 你好 world"), 2)

    def test_variance_zero_for_constant(self):
        self.assertEqual(score.variance([10, 10, 10]), 0.0)

    def test_variance_positive(self):
        self.assertGreater(score.variance([5, 50, 100]), 0)


class TestFingerprints(unittest.TestCase):
    def test_heavy_ai_high_score(self):
        hits, _ = score.scan_fingerprints(HEAVY_AI)
        s = score.fingerprint_score(hits)
        self.assertGreaterEqual(s, 5.0, f"AI 段指纹分应 ≥ 5，实际 {s}")

    def test_clean_human_low_score(self):
        hits, _ = score.scan_fingerprints(CLEAN_HUMAN)
        s = score.fingerprint_score(hits)
        self.assertLess(s, 3.0, f"人写段指纹分应 < 3，实际 {s}")

    def test_overlap_dedup(self):
        # "广泛应用" 和 "得到了广泛" 在原文有部分重叠
        text = "深度学习得到了广泛应用。"
        hits, _ = score.scan_fingerprints(text)
        # 去重后应保留显著度最高的，不应重复计算同一文本片段
        spans = [h.span for h in hits if h.span != (0, 0)]
        # 不应有完全相同的 span
        self.assertEqual(len(spans), len(set(spans)))

    def test_enumeration_S_plus(self):
        text = "首先做了 X。其次做了 Y。再次做了 Z。最后做了 W。"
        hits, _ = score.scan_fingerprints(text)
        sigs = [h.significance for h in hits]
        self.assertIn("S+", sigs, "首先...其次...再次...最后 应被识别为 S+ 指纹")


class TestSection(unittest.TestCase):
    def test_abstract_weight(self):
        rep = score.analyze_paragraph(HEAVY_AI, "test", section="abstract")
        # 加权应该 = 原始 * 1.8
        self.assertAlmostEqual(rep.fingerprint_score_weighted,
                               round(rep.fingerprint_score * 1.8, 2),
                               places=1)

    def test_ack_weight(self):
        rep = score.analyze_paragraph(HEAVY_AI, "test", section="ack")
        self.assertAlmostEqual(rep.fingerprint_score_weighted,
                               round(rep.fingerprint_score * 0.6, 2),
                               places=1)

    def test_default_weight(self):
        rep = score.analyze_paragraph(HEAVY_AI, "test")
        self.assertEqual(rep.fingerprint_score_weighted, rep.fingerprint_score)

    def test_citation_penalty_in_review(self):
        text = "在当今信息化时代，许多研究探讨了相关问题。一些学者从理论角度分析。"
        rep = score.analyze_paragraph(text, "test", section="literature_review")
        self.assertTrue(rep.citation_penalty)
        self.assertEqual(rep.risk, "high")


class TestRegister(unittest.TestCase):
    def test_colloquial_words_caught(self):
        violations = score.scan_register("这个方法真的很厉害，我觉得效果一堆。")
        rules = [v.rule for v in violations]
        self.assertIn("R1", rules)  # 我觉得
        self.assertIn("R2", rules)  # 真的、一堆

    def test_clean_text_no_violations(self):
        violations = score.scan_register(CLEAN_HUMAN)
        self.assertEqual(len(violations), 0)


class TestEvidence(unittest.TestCase):
    def test_numbers_counted(self):
        ev = score.scan_evidence("准确率 87.4%, p < 0.01, N = 500, β = 0.42")
        self.assertGreaterEqual(ev.numbers, 4)

    def test_citations_counted(self):
        ev = score.scan_evidence("Vaswani 等 (2017) 提出, 张三等 (2021) 报告")
        self.assertEqual(ev.citations, 2)

    def test_critical_perspective_counted(self):
        ev = score.scan_evidence("存在内生性偏倚，样本限制于 X，外部效度有限。")
        self.assertGreaterEqual(ev.critical_perspective, 3)


class TestReward(unittest.TestCase):
    def test_clean_better_than_ai(self):
        result = score.compute_reward(HEAVY_AI, CLEAN_HUMAN, section="abstract")
        # 改后应该指纹下降，痕迹增加
        self.assertGreater(result["scores"]["F"], 0.5)
        self.assertGreater(result["scores"]["E"], 0)
        self.assertGreater(result["scores"]["R_with_default_dQ"], 0.4)

    def test_register_gate_blocks(self):
        # 改后引入口语 → R = 0
        bad_after = "这方法真的很牛，我觉得效果好得不行。"
        result = score.compute_reward(HEAVY_AI, bad_after)
        self.assertEqual(result["scores"]["R_with_default_dQ"], 0.0)
        self.assertEqual(result["gates"]["register"], "FAIL")


class TestAdvanced(unittest.TestCase):
    """v2.3 段落级特征"""

    def test_punctuation_rhythm(self):
        # 顿号过密的 AI 风格
        text = "本研究、采用、双盲、随机、对照、试验、设计、分析。"
        rhythm = score.punctuation_rhythm(text)
        self.assertGreater(rhythm["dunhao_per_1k"], 8)

    def test_pronoun_inconsistency_warning(self):
        paras = ["本研究采用 X。", "我们使用 Y。", "笔者认为 Z。", "本文给出 W。"]
        result = score.detect_pronoun_inconsistency(paras)
        self.assertIsNotNone(result["warning"])

    def test_inter_paragraph_consistency(self):
        # 模拟两段 σ² 跳变巨大的情况
        from dataclasses import dataclass

        @dataclass
        class FakeReport:
            burstiness_sigma2: float

        reports = [FakeReport(20), FakeReport(400), FakeReport(15)]
        result = score.detect_inter_paragraph_consistency(reports)
        self.assertGreater(result["max_sigma2_jump"], 300)
        self.assertIsNotNone(result["warning"])

    def test_structural_homogeneity_high(self):
        # 三段开头都是"本研究"
        paras = [
            "本研究采用了实验方法。第一步预处理。第二步训练。第三步评估。",
            "本研究使用了 X 数据集。对其进行分析。结果如下。最后讨论。",
            "本研究构建了模型。模型由 A 组成。然后 B。最后是 C。",
        ]
        result = score.detect_structural_homogeneity(paras)
        self.assertGreater(result["structure_homogeneity_score"], 0.0)


class TestColloquial(unittest.TestCase):
    """v2.3 口语扫描与书面语度 W"""

    def test_watery_sample_hits(self):
        hits = score.scan_colloquial(WATERY_SAMPLE)
        joined = "".join(h.text for h in hits)
        for kw in ["在涨", "高出一截", "跟不上", "是这样的：",
                   "挡在", "绕开", "顺手", "帮了不少忙", "「"]:
            self.assertIn(kw, joined, f"应命中口语表达: {kw}")

    def test_clean_human_no_hits(self):
        self.assertEqual(len(score.scan_colloquial(CLEAN_HUMAN)), 0)

    def test_no_false_positive_formal(self):
        formal = "从结构来看，该方案存在涨幅约束；若条件不成立，则规避该路径，总结性的话语另述。"
        self.assertEqual([h.text for h in score.scan_colloquial(formal)], [])

    def test_formality_monotonic(self):
        self.assertLess(score.formality_score(WATERY_SAMPLE),
                        score.formality_score(CLEAN_HUMAN))

    def test_formality_gate_threshold(self):
        self.assertLess(score.formality_score(WATERY_SAMPLE), 0.6)
        self.assertGreaterEqual(score.formality_score(CLEAN_HUMAN), 0.6)

    def test_report_carries_formality(self):
        rep = score.analyze_paragraph(WATERY_SAMPLE, "t")
        self.assertLess(rep.formality, 0.6)
        self.assertGreater(len(rep.colloquial_hits), 5)


class TestRewardW(unittest.TestCase):
    """v2.3 W 进奖励公式"""

    def test_w_in_scores_and_weights(self):
        result = score.compute_reward(HEAVY_AI, CLEAN_HUMAN, section="abstract")
        self.assertIn("W", result["scores"])
        self.assertGreaterEqual(result["scores"]["W"], 0.6)
        self.assertEqual(result["gates"]["formality"], "PASS")

    def test_watery_after_fails_formality_gate(self):
        result = score.compute_reward(HEAVY_AI, WATERY_SAMPLE)
        self.assertEqual(result["gates"]["formality"], "FAIL")
        self.assertEqual(result["scores"]["R_with_default_dQ"], 0.0)


class TestRegisterMode(unittest.TestCase):
    """v2.3 --mode register CLI"""

    def test_register_mode_output(self):
        import io, json
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = score.main(["--mode", "register", "--text", WATERY_SAMPLE])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertIn("formality_W", out)
        self.assertEqual(out["w_gate"], "FAIL")
        self.assertGreater(len(out["colloquial_hits"]), 5)
        self.assertIn("register_violations", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
