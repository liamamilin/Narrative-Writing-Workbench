"""MockWritingEngine — deterministic, LLM-free engine for tests and offline dev.

Interface is identical to RealWritingEngine (both satisfy WritingEngine).
"""

from __future__ import annotations

from . import (DiscoveryFailed, GenerateResult, LockConflict,
               map_beats_to_paragraphs, split_paragraphs)

_MOCK_CANDIDATES = [
    {"id": "A1", "label": "The topic as loss", "mechanism": "subtraction",
     "core_question": "What is taken away?",
     "deep_meaning": "The topic names a loss the reader has not priced.",
     "reader_end_state": "the reader feels the missing thing precisely"},
    {"id": "A2", "label": "The topic as disguised self-question",
     "mechanism": "projection",
     "core_question": "What does the reader really ask about themselves?",
     "deep_meaning": "The topic stands in for a question about identity.",
     "reader_end_state": "the reader recognizes their own question"},
    {"id": "A3", "label": "The topic as revaluation", "mechanism": "repricing",
     "core_question": "What changes value once the topic is faced?",
     "deep_meaning": "The topic re-prices what the reader already paid.",
     "reader_end_state": "the reader sees past effort in a new light"},
]

_MOCK_TOPICS = [
    # self
    {"domain": "self", "sub": "self.freedom",
     "text": "自律不是自由,是自我驯化。", "hook": "纪律到底是解放还是枷锁"},
    {"domain": "self", "sub": "self.meaning",
     "text": "人生越充实,越难回答为什么活着。", "hook": "忙碌是不是逃避"},
    {"domain": "self", "sub": "self.desire",
     "text": "忍住欲望的人,输掉的比得到的多。", "hook": "节制会不会是损失"},
    {"domain": "self", "sub": "self.solitude",
     "text": "怕孤独的人,其实怕的是自己。", "hook": "独处照出什么"},
    {"domain": "self", "sub": "self.identity",
     "text": "人设演久了,真身就没了。", "hook": "扮演何时反噬"},
    {"domain": "self", "sub": "self.growth",
     "text": "成长的一半是失去,只是没人结算。", "hook": "长大换走了什么"},
    # relations
    {"domain": "relations", "sub": "relations.love",
     "text": "爱得越用力,越像是在控制。", "hook": "在乎和占有的边界"},
    {"domain": "relations", "sub": "relations.friendship",
     "text": "朋友是没用处的,有用处的是人脉。", "hook": "友谊要不要有用"},
    {"domain": "relations", "sub": "relations.family",
     "text": "家人之间,最需要的是距离。", "hook": "亲密如何不越界"},
    {"domain": "relations", "sub": "relations.trust",
     "text": "信任不是因为对方可靠,是因为我们没得选。", "hook": "信任的真相"},
    {"domain": "relations", "sub": "relations.empathy",
     "text": "共情是捷径,也是偷懒。", "hook": "我懂你懂了什么"},
    {"domain": "relations", "sub": "relations.debt",
     "text": "报恩是把亏欠变成权力的方式。", "hook": "恩情是谁的筹码"},
    # society
    {"domain": "society", "sub": "society.rules",
     "text": "例外一多,规则就成了装饰。", "hook": "特权的入口在哪"},
    {"domain": "society", "sub": "society.equality",
     "text": "追求平等时,公平常常先死。", "hook": "两种善的打架"},
    {"domain": "society", "sub": "society.power",
     "text": "免责的权力不是权力,是特权。", "hook": "责任去哪了"},
    {"domain": "society", "sub": "society.majority",
     "text": "多数人点头,不等于事情是对的。", "hook": "人数与正确无关"},
    {"domain": "society", "sub": "society.mercy",
     "text": "原谅被滥用后,惩罚反而更珍贵。", "hook": "宽恕的代价"},
    {"domain": "society", "sub": "society.mobility",
     "text": "向上流动的故事,治好了谁的不平等。", "hook": "通道还是麻醉"},
    # work
    {"domain": "work", "sub": "work.diligence",
     "text": "勤劳是奴隶的道德。", "hook": "为什么勤奋反成枷锁"},
    {"domain": "work", "sub": "work.mastery",
     "text": "太专业的人,看不见专业外的世界。", "hook": "专业的盲区"},
    {"domain": "work", "sub": "work.creation",
     "text": "收藏不等于拥有,消费正在冒充创造。", "hook": "你真的做过吗"},
    {"domain": "work", "sub": "work.hustle",
     "text": "松弛不是休息,是对内卷的罢工。", "hook": "躺平的政治学"},
    {"domain": "work", "sub": "work.craft",
     "text": "流量时代,匠心是一种亏本的美德。", "hook": "慢工为什么吃亏"},
    {"domain": "work", "sub": "work.failure",
     "text": "失败教会人的,大多是驯服。", "hook": "挫折真能磨砺吗"},
    # tech
    {"domain": "tech", "sub": "tech.ai",
     "text": "AI 替你思考之前,先替你放弃了思考。", "hook": "外包了什么"},
    {"domain": "tech", "sub": "tech.convenience",
     "text": "便利不是省时间,是把时间交给别人。", "hook": "谁赚走你的耐心"},
    {"domain": "tech", "sub": "tech.connection",
     "text": "越连接,越孤独。", "hook": "在线为何更冷"},
    {"domain": "tech", "sub": "tech.speed",
     "text": "提速省下的时间,被更快的浪费吃掉了。", "hook": "快真的值吗"},
    {"domain": "tech", "sub": "tech.privacy",
     "text": "透明不是美德,是弱者的义务。", "hook": "谁被要求透明"},
    {"domain": "tech", "sub": "tech.progress",
     "text": "进步的总账,从来没人敢算。", "hook": "代价记在谁头上"},
    # truth
    {"domain": "truth", "sub": "truth.expertise",
     "text": "专家的常识,常常过期而不自知。", "hook": "权威的保质期"},
    {"domain": "truth", "sub": "truth.memory",
     "text": "记忆不是存档,是每次都在重写。", "hook": "过去被谁改写"},
    {"domain": "truth", "sub": "truth.doubt",
     "text": "什么都不信的人,最先信了怀疑。", "hook": "怀疑也是信仰"},
    {"domain": "truth", "sub": "truth.narrative",
     "text": "事实是素材,叙事才是判决。", "hook": "谁在组织事实"},
    {"domain": "truth", "sub": "truth.ignorance",
     "text": "知道得越少,行动越果断。", "hook": "无知为何轻盈"},
    {"domain": "truth", "sub": "truth.lies",
     "text": "善意的谎言,是信任的预付款。", "hook": "谎话买来什么"},
    # time
    {"domain": "time", "sub": "time.ending",
     "text": "结束不是终点,是理解的开始。", "hook": "为什么事后才懂"},
    {"domain": "time", "sub": "time.busy",
     "text": "忙,是最体面的逃避。", "hook": "忙碌躲开了什么"},
    {"domain": "time", "sub": "time.nostalgia",
     "text": "怀念的不是过去,是当时的自己。", "hook": "乡愁的对象"},
    {"domain": "time", "sub": "time.aging",
     "text": "变老不是失去时间,是终于有了时间。", "hook": "年龄的另一面"},
    {"domain": "time", "sub": "time.nature",
     "text": "人不是自然的主人,是自然最吵的客人。", "hook": "谁在谁家做客"},
    {"domain": "time", "sub": "time.renewal",
     "text": "灾难不长教训,只长记性。", "hook": "教训为何复发"},
    # art
    {"domain": "art", "sub": "art.useful",
     "text": "无用的东西,才撑得起美。", "hook": "美为什么要无用"},
    {"domain": "art", "sub": "art.kitsch",
     "text": "媚俗不是品味低,是情感的批发。", "hook": "感动被谁量产"},
    {"domain": "art", "sub": "art.imperfect",
     "text": "完美是作品的死亡证书。", "hook": "残缺为何动人"},
    {"domain": "art", "sub": "art.silence",
     "text": "说得越满,留白越少,作品越穷。", "hook": "沉默的分量"},
    {"domain": "art", "sub": "art.originality",
     "text": "所谓原创,是把偷来的东西消化干净。", "hook": "原创的来历"},
    {"domain": "art", "sub": "art.ethics",
     "text": "艺术不能豁免道德,但能换算它。", "hook": "天才的折扣"},
]

_MockTopicState_cycle = [0]


class _MockTopicState:
    @staticmethod
    def next_start() -> int:
        _MockTopicState_cycle[0] += 1
        return _MockTopicState_cycle[0]

    @staticmethod
    def reset() -> None:
        _MockTopicState_cycle[0] = 0


_MOCK_WIR = {    "kind": "mock_wir",
    "beats": [
        {"id": "B1", "function": {"primary": "ground"},
         "reader_transition": {"from": "curious", "to": "oriented"},
         "meaning_gain": "reader learns the situation"},
        {"id": "B2", "function": {"primary": "complicate"},
         "reader_transition": {"from": "oriented", "to": "tense"},
         "meaning_gain": "the tension becomes felt"},
        {"id": "B3", "function": {"primary": "turn"},
         "reader_transition": {"from": "tense", "to": "shifted"},
         "meaning_gain": "the meaning pivots on a detail"},
        {"id": "B4", "function": {"primary": "land"},
         "reader_transition": {"from": "shifted", "to": "settled"},
         "meaning_gain": "the reader sits with the aftertaste"},
    ],
}


class MockWritingEngine:
    name = "mock"
    simulate_repair = False    # tests flip this to exercise the reset path

    def discover_meaning(self, *, topic, writing_mode, angle_mode,
                         custom_angle, avoid, config, emit=None,
                         on_delta=None) -> dict:
        if emit:
            emit("stage", {"stage": "discovery"})
        if not topic.strip():
            raise DiscoveryFailed("Enter a topic to write about.")
        if on_delta:
            on_delta("{\"topic\": …}  # mock discovery")
        if angle_mode == "custom":
            candidates = [dict(_MOCK_CANDIDATES[0])]
            candidates[0].update({"id": "A0", "label": custom_angle})
            selected = "A0"
        else:
            candidates = [dict(c) for c in _MOCK_CANDIDATES]
            fresh = [c for c in candidates if c["label"] not in set(avoid or [])]
            if not fresh:
                raise DiscoveryFailed("No distinct angles remain to try.")
            selected = fresh[-1]["id"] if len(fresh) > 1 else fresh[0]["id"]
        sel = next(c for c in candidates if c["id"] == selected)
        return {
            "topic": topic, "surface_question": f"Why {topic}?",
            "candidate_tensions": ["wanting it vs. fearing it"],
            "candidate_angles": candidates,
            "selected_angle_id": selected,
            "selection_reason": "mock: most generative framing",
            "core_question": sel["core_question"],
            "deep_meaning": sel["deep_meaning"],
            "common_reading": "a generic answer",
            "new_reading": sel["deep_meaning"],
            "reader_end_state": sel["reader_end_state"],
            "key_tensions": ["wanting vs. fearing"],
            "constraints": [], "fact_heavy": False, "language": "en",
        }

    def generate(self, *, material, instruction, task_type, config,
                 meaning=None, emit=None, on_delta=None,
                 on_struct_delta=None) -> GenerateResult:
        if emit:
            emit("stage", {"stage": "structure"})
            if on_struct_delta:
                on_struct_delta("{\"beats\": […]}  # mock structure")
            emit("stage_summary", {"stage": "structure",
                                   "text": "结构:铺垫 → 张力显形 → 转折 → 收束"})
            emit("stage", {"stage": "writing"})
        topic = (instruction or material or "the subject").strip().split("\n")[0][:40]
        if meaning and meaning.get("selected_angle"):
            topic = f"{topic} — {meaning['selected_angle']}".strip(" —")[:80]
        paras = [
            f"{topic} began quietly, in a way no one thought to record.",
            "The details accumulated: a door left open, a sentence repeated, "
            "and a small silence at the far end of the table that nobody named.",
            "What mattered was never said directly, only circled.",
            "By the end, the reader understands what the character refused to.",
        ]
        plan = dict(_MOCK_WIR)
        if meaning:
            plan["meaning"] = meaning
        text = "\n\n".join(paras)
        if on_delta:
            import time as _t
            if self.simulate_repair:
                # exercise the UI's reset/clear path mid-stream
                half = len(text) // 2
                for i in range(0, half, 24):
                    on_delta(text[i:i + 24])
                on_delta("", True)
                for i in range(0, len(text), 24):
                    on_delta(text[i:i + 24])
                    _t.sleep(0.005)
            else:
                for i in range(0, len(text), 24):
                    on_delta(text[i:i + 24])
                    _t.sleep(0.005)
        return GenerateResult(text=text, plan=plan)

    def review(self, *, content, material, instruction, plan, config,
               on_delta=None) -> dict:
        if on_delta:
            on_delta("{\"quality\": {…}}  # mock review")
        paras = split_paragraphs(content)
        issues = []
        for i, p in enumerate(paras, 1):
            if len(p) > 90:
                issues.append({
                    "id": f"issue_{i}",
                    "location": {"paragraph_start": i, "paragraph_end": i},
                    "type": "over_explanation",
                    "message": "This paragraph may explain more than the reader needs.",
                    "fixable": True,
                })
        return {
            "summary": {
                "progression": "strong",
                "meaning_density": "good",
                "immersion": "good",
                "restraint": "needs_attention" if issues else "good",
                "coherence": "strong",
            },
            "issues": issues,
        }

    def patch(self, *, content, before_text, instruction, locks, config) -> str:
        if locks.get("facts") and "invent" in instruction.lower():
            raise LockConflict("This revision would alter source facts.")
        if "shorter" in instruction.lower() or "shorten" in instruction.lower():
            after = before_text[: max(20, len(before_text) // 2)].rstrip() + "。"
        else:
            after = before_text.replace("  ", " ").strip()
            if after == before_text:
                after = before_text.rstrip().removesuffix(".") + " — and it settled there."
        return after

    def writing_map(self, *, plan, content) -> list[dict]:
        beats = (plan or {}).get("beats", _MOCK_WIR["beats"])
        return map_beats_to_paragraphs(beats, content)

    def suggest_instruction(self, *, material, topic, task_type,
                            instruction, config, language,
                            meaning=None, avoid=None) -> str:
        if instruction:
            return ("精炼现有写作意图:保留你的观点与事实主张,收紧语言,"
                    "并明确读者读完后应产生的具体感受。")
        if topic:
            return f"围绕“{topic}”,用具体细节而非抽象口号,让读者自己感到其中的分量。"
        if material:
            return ("从一个具体细节出发,把素材里最反常的事情推到读者面前,"
                    "不直接说出结论。")
        return "给出一个具体场景,让读者感到这次经历的分量,不直接说出结论。"

    def suggest_topics(self, *, domain=None, sub=None,
                       avoid=None, config=None) -> dict:
        """Deterministic canned candidates (LLM-free), avoid-list honored.

        The pool start rotates per call, so an immediate re-roll (without
        avoid) still yields a different trio.
        """
        pool = [t for t in _MOCK_TOPICS
                if (not domain or t["domain"] == domain)
                and (not sub or t["sub"] == sub)]
        if not pool:
            pool = list(_MOCK_TOPICS)
        banned = {a.strip() for a in (avoid or []) if a and a.strip()}
        start = _MockTopicState.next_start()
        rotated = pool[start % len(pool):] + pool[:start % len(pool)]
        picks = [t for t in rotated if t["text"] not in banned]
        return {"topics": [{"text": t["text"], "hook": t["hook"]}
                           for t in picks[:3]]}
