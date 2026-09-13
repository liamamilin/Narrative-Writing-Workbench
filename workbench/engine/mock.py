"""MockWritingEngine — deterministic, LLM-free engine for tests and offline dev.

Interface is identical to RealWritingEngine (both satisfy WritingEngine).
"""

from __future__ import annotations

from . import (DiscoveryFailed, GenerationFailed, GenerateResult,
               LockConflict, map_beats_to_paragraphs, split_paragraphs)

_MOCK_CANDIDATES = [
    {"id": "A1", "label": "The topic as loss", "mechanism": "subtraction",
     "core_question": "What is taken away?",
     "deep_meaning": "The topic names a loss the reader has not priced.",
     "reader_end_state": "the reader feels the missing thing precisely",
     "crack": "the usual account ignores what disappears",
     "strongest_counterexample": "some losses are chosen and fully understood",
     "boundary": "holds for unpriced loss, not deliberate exchange"},
    {"id": "A2", "label": "The topic as disguised self-question",
     "mechanism": "projection",
     "core_question": "What does the reader really ask about themselves?",
     "deep_meaning": "The topic stands in for a question about identity.",
     "reader_end_state": "the reader recognizes their own question",
     "crack": "the surface question never resolves the repeated unease",
     "strongest_counterexample": "some questions are simply about the object",
     "boundary": "holds when the question repeats across different objects"},
    {"id": "A3", "label": "The topic as revaluation", "mechanism": "repricing",
     "core_question": "What changes value once the topic is faced?",
     "deep_meaning": "The topic re-prices what the reader already paid.",
     "reader_end_state": "the reader sees past effort in a new light",
     "crack": "past effort changes meaning after the outcome",
     "strongest_counterexample": "some past costs keep the same value",
     "boundary": "holds where outcomes change the story attached to effort"},
]

_MOCK_CANDIDATES_ALT = [
    {**_MOCK_CANDIDATES[0], "id": "A1", "label": "The topic as a threshold",
     "mechanism": "phase change"},
    {**_MOCK_CANDIDATES[1], "id": "A2", "label": "The topic as borrowed language",
     "mechanism": "imitation"},
    {**_MOCK_CANDIDATES[2], "id": "A3", "label": "The topic as delayed choice",
     "mechanism": "option cost"},
]

_MOCK_TOPICS = [
    # 每条标多个 domain(taxonomy v2 Surface Domain)+ 若干 tension(t01..t33);
    # 覆盖不变式:每个 domain ≥3 条、每个 tension ≥2 条(tests 断言)。
    {"text": "勤劳是奴隶的道德。", "hook": "勤奋怎么成了枷锁",
     "domains": ["labor", "philosophy", "history"], "tensions": ["t28", "t02"]},
    {"text": "用勤奋逃避思考,是最隐蔽的懒惰。", "hook": "勤奋为何成了懒惰",
     "domains": ["labor", "education", "psychology"], "tensions": ["t32", "t26"]},
    {"text": "加班不是勤奋,是效率低下的遮羞布。", "hook": "加班是勤奋吗",
     "domains": ["labor", "business", "economy"], "tensions": ["t05", "t21"]},
    {"text": "学历是正在通胀的货币。", "hook": "Goodhart Trap:学历失真",
     "domains": ["education", "labor", "class"], "tensions": ["t26", "t05"]},
    {"text": "没人敢第一个给孩子减负。", "hook": "个体理性陷阱",
     "domains": ["education", "parenting", "class"], "tensions": ["t28", "t06"]},
    {"text": "补习越多,越不知道自己喜欢什么。", "hook": "培训偷走了什么",
     "domains": ["education", "parenting", "psychology"], "tensions": ["t26", "t16"]},
    {"text": "AI 替你思考之前,先替你放弃了思考。", "hook": "Convenience Trap",
     "domains": ["ai", "tech", "internet"], "tensions": ["t32", "t33"]},
    {"text": "越方便的工具,越难离开。", "hook": "便利怎么变绑架",
     "domains": ["tech", "internet", "consumer"], "tensions": ["t32", "t08"]},
    {"text": "算法不是在推荐,是在替你决定。", "hook": "选择权去哪了",
     "domains": ["internet", "socialmedia", "ai"], "tensions": ["t07", "t28"]},
    {"text": "免费的产品里,你才是被卖的东西。", "hook": "Hidden Cost Bearer",
     "domains": ["internet", "media", "business"], "tensions": ["t17", "t16"]},
    {"text": "信息越多,越难知道真相。", "hook": "信息越多越糟",
     "domains": ["media", "socialmedia", "psychology"], "tensions": ["t30", "t16"]},
    {"text": "热搜不是新闻,是注意力的期货。", "hook": "流量在交易什么",
     "domains": ["media", "entertainment", "economy"], "tensions": ["t20"]},
    {"text": "越连接,越孤独。", "hook": "在线为何更冷",
     "domains": ["internet", "socialmedia", "love"], "tensions": ["t19", "t16"]},
    {"text": "群聊越热闹,真话越少。", "hook": "表达为何变表演",
     "domains": ["socialmedia", "psychology", "culture"], "tensions": ["t16", "t25"]},
    {"text": "婚姻没变,变的是对婚姻的期待。", "hook": "期待如何拖垮婚姻",
     "domains": ["family", "love", "intimacy"], "tensions": ["t11", "t19"]},
    {"text": "爱得越用力,越像控制。", "hook": "Dependency Power",
     "domains": ["love", "intimacy", "psychology"], "tensions": ["t19", "t18"]},
    {"text": "越亲密,越难谈钱。", "hook": "亲密的边界失语",
     "domains": ["intimacy", "love", "family"], "tensions": ["t19", "t29"]},
    {"text": "父母给得越多,孩子越难长大。", "hook": "爱的通胀",
     "domains": ["family", "parenting", "psychology"], "tensions": ["t19", "t28"]},
    {"text": "养老越专业,亲情越外包。", "hook": "照料的边界",
     "domains": ["aging", "family", "medicine"], "tensions": ["t19", "t05"]},
    {"text": "健康的定义越多,焦虑越多。", "hook": "健康在贩卖什么",
     "domains": ["health", "medicine", "consumer"], "tensions": ["t16", "t29"]},
    {"text": "心理标签越多,自我越模糊。", "hook": "标签替代了自知",
     "domains": ["psychology", "socialmedia", "culture"], "tensions": ["t16", "t09"]},
    {"text": "独处越难,人格越依赖观众。", "hook": "谁在替你定义你",
     "domains": ["psychology", "philosophy", "socialmedia"], "tensions": ["t18"]},
    {"text": "规则越多,可信的越少。", "hook": "信任被外包了吗",
     "domains": ["law", "governance", "business"], "tensions": ["t14"]},
    {"text": "惩罚越重,越没人认错。", "hook": "威慑的反效果",
     "domains": ["law", "crime", "governance"], "tensions": ["t15"]},
    {"text": "打击越狠,犯罪越隐蔽。", "hook": "打击推动演化",
     "domains": ["crime", "law", "tech"], "tensions": ["t27", "t10"]},
    {"text": "越安全的系统,越怕小概率。", "hook": "Safety Paradox",
     "domains": ["governance", "tech", "city"], "tensions": ["t03", "t22"]},
    {"text": "城市越干净,越容不下穷人。", "hook": "整洁驱逐了谁",
     "domains": ["city", "class", "governance"], "tensions": ["t04", "t07"]},
    {"text": "房子越多,越买不起房。", "hook": "供给为何失灵",
     "domains": ["realestate", "economy", "population"], "tensions": ["t24", "t05"]},
    {"text": "城市越大,通勤越长。", "hook": "城市在奖励什么",
     "domains": ["city", "transport", "class"], "tensions": ["t05", "t20"]},
    {"text": "高铁越快,小站越荒。", "hook": "快线抛弃了谁",
     "domains": ["transport", "city", "economy"], "tensions": ["t05", "t25"]},
    {"text": "打车越方便,公交越萎缩。", "hook": "慢车被快钱挤走",
     "domains": ["transport", "city", "class"], "tensions": ["t05", "t04"]},
    {"text": "地铁越修越远,通勤越修越长。", "hook": "长度不是速度",
     "domains": ["transport", "city", "realestate"], "tensions": ["t05", "t20"]},
    {"text": "学区房越贵,教育越偏。", "hook": "入学资格的商品化",
     "domains": ["realestate", "education", "class"], "tensions": ["t04", "t26"]},
    {"text": "风控越严,越只借钱给不需要的人。", "hook": "Gatekeeper",
     "domains": ["finance", "economy", "business"], "tensions": ["t14", "t05"]},
    {"text": "富人越避税,中产越承重。", "hook": "Hidden Cost Bearer",
     "domains": ["finance", "politics", "class"], "tensions": ["t24", "t05"]},
    {"text": "创业越自由,越被资本定义。", "hook": "自主的代价",
     "domains": ["startup", "finance", "business"], "tensions": ["t18", "t28"]},
    {"text": "越考核创新,越没人试错。", "hook": "Goodhart Trap",
     "domains": ["management", "business", "governance"], "tensions": ["t14", "t10"]},
    {"text": "团队越大,决策越慢。", "hook": "Bureaucracy Emergence",
     "domains": ["management", "startup", "governance"], "tensions": ["t21", "t31"]},
    {"text": "越透明的考核,越没人说真话。", "hook": "Transparency Paradox",
     "domains": ["management", "socialmedia", "internet"], "tensions": ["t17", "t16"]},
    {"text": "坏消息爬楼越爬越少。", "hook": "Bad-News Suppression",
     "domains": ["management", "governance", "psychology"], "tensions": ["t17", "t16"]},
    {"text": "选票越频繁,决策越短视。", "hook": "选票偏爱眼前",
     "domains": ["politics", "governance", "history"], "tensions": ["t20", "t12"]},
    {"text": "国际规则越多,越只约束守规者。", "hook": "规则为谁而立",
     "domains": ["intl", "politics", "history"], "tensions": ["t05", "t07"]},
    {"text": "武器越精准,开战越便宜。", "hook": "门槛在下降",
     "domains": ["war", "intl", "tech"], "tensions": ["t33", "t20"]},
    {"text": "和平越久,越像免费的运气。", "hook": "和平的账单",
     "domains": ["war", "history", "politics"], "tensions": ["t20", "t16"]},
    {"text": "侦察越清晰,误判越危险。", "hook": "确定性制造盲区",
     "domains": ["war", "intl", "politics"], "tensions": ["t30", "t33"]},
    {"text": "粮食越丰收,农民越亏本。", "hook": "增产不增收",
     "domains": ["agriculture", "food", "economy"], "tensions": ["t24", "t05"]},
    {"text": "农村越现代化,越留不住人。", "hook": "谁被现代化带走",
     "domains": ["agriculture", "population", "class"], "tensions": ["t28", "t20"]},
    {"text": "能源越便宜,浪费越正当。", "hook": "补贴在奖励什么",
     "domains": ["energy", "industry", "environment"], "tensions": ["t23", "t20"]},
    {"text": "电网越智能,停电越致命。", "hook": "冗余被优化掉",
     "domains": ["energy", "city", "tech"], "tensions": ["t22", "t21"]},
    {"text": "环保越严,污染越搬家。", "hook": "边界外的代价",
     "domains": ["environment", "industry", "intl"], "tensions": ["t27", "t07"]},
    {"text": "增长考核越硬,环境账越贵。", "hook": "增长的隐藏账单",
     "domains": ["environment", "economy", "industry"], "tensions": ["t23", "t20"]},
    {"text": "环保越时髦,消费越环保化。", "hook": "赎罪券经济学",
     "domains": ["environment", "consumer", "fashion"], "tensions": ["t16", "t24"]},
    {"text": "人口越少,竞争越烈。", "hook": "收缩时代的挤压",
     "domains": ["population", "economy", "labor"], "tensions": ["t28", "t06"]},
    {"text": "越长寿,越谈不好死亡。", "hook": "技术推迟了告别",
     "domains": ["medicine", "aging", "philosophy"], "tensions": ["t16", "t15"]},
    {"text": "预期能活越久,越不敢停下。", "hook": "时间的通胀",
     "domains": ["aging", "labor", "economy"], "tensions": ["t20", "t24"]},
    {"text": "疫苗越有效,接种越犹豫。", "hook": "Safety Paradox 再版",
     "domains": ["medicine", "health", "socialmedia"], "tensions": ["t03", "t16"]},
    {"text": "预印本越多,论文越难信。", "hook": "发表的通胀",
     "domains": ["science", "education", "internet"], "tensions": ["t26", "t16"]},
    {"text": "指标越好,实验室越空。", "hook": "考核替代发现",
     "domains": ["science", "education", "management"], "tensions": ["t14", "t26"]},
    {"text": "外卖越多,厨房越静。", "hook": "Convenience Trap",
     "domains": ["food", "consumer", "labor"], "tensions": ["t32", "t16"]},
    {"text": "越是丰收,越吃不出味道。", "hook": "丰盛钝化了味觉",
     "domains": ["food", "travel", "consumer"], "tensions": ["t16"]},
    {"text": "攻略越多,旅途越雷同。", "hook": "便利的复制品",
     "domains": ["travel", "consumer", "socialmedia"], "tensions": ["t09", "t16"]},
    {"text": "景点越出名,风景越消失。", "hook": "Prestige Cascade",
     "domains": ["travel", "culture", "consumer"], "tensions": ["t09", "t25"]},
    {"text": "博物馆越火,看画越少。", "hook": "艺术的背景化",
     "domains": ["art", "culture", "consumer"], "tensions": ["t16", "t25"]},
    {"text": "艺术越被讲解,越难被感受。", "hook": "解读替代了体验",
     "domains": ["art", "culture", "education"], "tensions": ["t16", "t12"]},
    {"text": "直播越多,手艺越少。", "hook": "流量抽干耐心",
     "domains": ["art", "games", "internet"], "tensions": ["t32", "t20"]},
    {"text": "翻译越快,外语越没人学。", "hook": "工具替代能力",
     "domains": ["culture", "literature", "ai"], "tensions": ["t32", "t31"]},
    {"text": "读书越普及,深读越稀少。", "hook": "阅读的降维",
     "domains": ["literature", "education", "philosophy"], "tensions": ["t26", "t16"]},
    {"text": "经典越被引用,越少被阅读。", "hook": "符号代替了文本",
     "domains": ["literature", "culture", "media"], "tensions": ["t16", "t25"]},
    {"text": "游戏越真实,现实越无趣。", "hook": "虚拟的引力",
     "domains": ["games", "entertainment", "psychology"], "tensions": ["t16", "t32"]},
    {"text": "联赛越商业,快乐越稀薄。", "hook": "竞技取代游戏",
     "domains": ["sports", "entertainment", "business"], "tensions": ["t05", "t24"]},
    {"text": "健身越流行,身体越像任务。", "hook": "健康的KPI化",
     "domains": ["sports", "health", "consumer"], "tensions": ["t28", "t29"]},
    {"text": "电竞越职业,玩心越少。", "hook": "游戏的在职化",
     "domains": ["games", "entertainment", "business"], "tensions": ["t11", "t10"]},
    {"text": "神话越淡,庙越香。", "hook": "祛魅的代价",
     "domains": ["religion", "philosophy", "history"], "tensions": ["t11", "t29"]},
    {"text": "越强调孝顺,越难相处。", "hook": "义务挤占了爱",
     "domains": ["family", "parenting", "culture"], "tensions": ["t19", "t11"]},
    {"text": "历史越普及,越像消费。", "hook": "记忆的快消化",
     "domains": ["history", "media", "culture"], "tensions": ["t20", "t16"]},
    {"text": "潮牌越流行,风格越死。", "hook": "快时尚杀死风格",
     "domains": ["fashion", "consumer", "culture"], "tensions": ["t11", "t09"]},
    {"text": "名牌越便宜,身份越焦虑。", "hook": "符号在贬值",
     "domains": ["fashion", "consumer", "class"], "tensions": ["t25", "t29"]},
    {"text": "快递越快,包裹越没人拆。", "hook": "消费的疲劳",
     "domains": ["consumer", "labor", "economy"], "tensions": ["t20", "t16"]},
    {"text": "越多人跑步,越没人散步。", "hook": "健康的任务化",
     "domains": ["sports", "health", "psychology"], "tensions": ["t28", "t29"]},
    {"text": "科学越开放,造假越隐蔽。", "hook": "同行评议的失灵",
     "domains": ["science", "internet", "governance"], "tensions": ["t07", "t16"]},
    {"text": "监控越密,安全越依赖镜头。", "hook": "看守的日常化",
     "domains": ["crime", "city", "tech"], "tensions": ["t03", "t17"]},
    {"text": "慈善越透明,善款越难筹。", "hook": "Transparency Paradox",
     "domains": ["governance", "finance", "class"], "tensions": ["t17", "t15"]},
    {"text": "对个人理性的选择,正在集体埋单。", "hook": "个体理性陷阱",
     "domains": ["economy", "environment", "class"], "tensions": ["t01", "t28"]},
    {"text": "自愿的加班,抬高所有人的门槛。", "hook": "个人的理性集体的坏",
     "domains": ["labor", "education", "business"], "tensions": ["t01", "t28"]},
    {"text": "管得越细,基层越不会走路。", "hook": "Centralization Pressure",
     "domains": ["governance", "politics", "management"], "tensions": ["t13", "t12"]},
    {"text": "越放权,基层越得自己扛。", "hook": "自治与兜底的落差",
     "domains": ["governance", "city", "finance"], "tensions": ["t13", "t28"]},
    {"text": "秩序越安全,自由越隐形。", "hook": "看不见的收缩",
     "domains": ["law", "governance", "philosophy"], "tensions": ["t02", "t03"]},
    {"text": "为了方便,我们把隐私免费送了。", "hook": "Privacy Paradox",
     "domains": ["tech", "internet", "consumer"], "tensions": ["t08", "t17"]},
    {"text": "种子越改良,农民越不拥有它。", "hook": "谁的种子",
     "domains": ["agriculture", "law", "business"], "tensions": ["t24", "t27"]},
    {"text": "产业越自动化,越怕断供。", "hook": "Automatic Lock-in",
     "domains": ["industry", "tech", "intl"], "tensions": ["t21", "t33"]},
    {"text": "转型越急,旧资产越顽固。", "hook": "Lock-in 的阻力",
     "domains": ["energy", "finance", "industry"], "tensions": ["t11", "t20"]},
    {"text": "风口越多,越没人做慢生意。", "hook": "信号背离实质",
     "domains": ["startup", "business", "finance"], "tensions": ["t20", "t26"]},
    {"text": "信仰越便利,敬畏越稀薄。", "hook": "祛魅的另一面",
     "domains": ["religion", "internet", "psychology"], "tensions": ["t32", "t16"]},
    {"text": "越世俗化,越需要意义商品。", "hook": "神圣的再生产",
     "domains": ["religion", "culture", "consumer"], "tensions": ["t11", "t16"]},
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
    fail_writer = False        # tests flip this to fail AFTER the plan node

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
            candidates = [dict(c) for c in _MOCK_CANDIDATES]
            candidates[0].update({"id": "A0", "label": custom_angle})
            selected = "A0"
        else:
            pool = (_MOCK_CANDIDATES_ALT
                    if all(c["label"] in set(avoid or [])
                           for c in _MOCK_CANDIDATES)
                    else _MOCK_CANDIDATES)
            candidates = [dict(c) for c in pool]
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
            "crack": sel["crack"],
            "strongest_counterexample": sel["strongest_counterexample"],
            "boundary": sel["boundary"],
            "refined_thesis": f"{sel['deep_meaning']} — priced differently",
            "key_tensions": ["wanting vs. fearing"],
            "constraints": [], "fact_heavy": False, "language": "en",
        }

    def generate(self, *, material, instruction, task_type, config,
                 meaning=None, emit=None, on_delta=None,
                 on_struct_delta=None, plan=None,
                 on_plan=None) -> GenerateResult:
        reused = bool(plan)
        if emit:
            if reused:
                emit("stage", {"stage": "structure"})
                emit("stage_summary", {"stage": "structure",
                                       "text": "结构:复用上次结构"})
            else:
                emit("stage", {"stage": "structure"})
                if on_struct_delta:
                    on_struct_delta("{\"beats\": […]}  # mock structure")
                emit("stage_summary", {"stage": "structure",
                                       "text": "结构:铺垫 → 张力显形 → 转折 → 收束"})
            emit("stage", {"stage": "writing"})
        if reused:
            plan_data = plan
        else:
            plan_data = dict(_MOCK_WIR)
            if meaning:
                plan_data["meaning"] = meaning
            if on_plan:
                on_plan(plan_data)
        if self.fail_writer:
            raise GenerationFailed("mock writer failure")
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
        return GenerateResult(text=text, plan=plan_data)

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
                    "severity": "moderate",
                    "message": "This paragraph may explain more than the reader needs.",
                    "effect": "It leaves less room for the reader to infer the meaning.",
                    "goal": "Make this shorter while preserving the concrete meaning.",
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

    def suggest_topics(self, *, domain=None, object_name=None, tension=None,
                       avoid=None, config=None, count=8, hint=None,
                       seed=None) -> dict:
        """Deterministic canned candidates (LLM-free), avoid-list honored.

        Entries carry multiple domain tags; object filtering matches the
        object name as a substring of the canned text (Concrete Anchor
        heuristic; unmatched objects roam the whole pool). A `seed` (the
        user's own thinking) filters canned topics whose text/hook contains
        it as a substring, roaming the whole pool when nothing matches.
        The pool start rotates per call so an immediate re-roll (without
        avoid) still yields a fresh slice. `hint` is a real-engine-only
        steer and is ignored here. Effective count is capped at the pool
        size so a batch never repeats within itself.
        """
        pool = [t for t in _MOCK_TOPICS
                if (not domain or domain in t["domains"])
                and (not object_name or object_name in t["text"]
                     or object_name in t["hook"])
                and (not tension or tension in t["tensions"])]
        seed = (seed or "").strip()
        if seed:
            hits = [t for t in pool if seed in t["text"] or seed in t["hook"]]
            pool = hits or pool
        if not pool:
            pool = list(_MOCK_TOPICS)
        banned = {a.strip() for a in (avoid or []) if a and a.strip()}
        start = _MockTopicState.next_start()
        rotated = pool[start % len(pool):] + pool[:start % len(pool)]
        picks = [t for t in rotated if t["text"] not in banned]
        n = max(3, min(int(count or 8), len(picks) or 1))
        return {"topics": [{"text": t["text"], "hook": t["hook"]}
                           for t in picks[:n]]}
