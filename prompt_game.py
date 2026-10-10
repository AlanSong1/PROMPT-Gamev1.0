# -*- coding: utf-8 -*-
"""
PROMPT —— 提示词写作游戏（原型）
玩家阅读「任务背景 + 具体任务」，撰写一条提示词交给 AI 完成任务。
系统按该任务的场景与目标自适应地生成评分维度与权重，逐项打分并给出反馈。
"""

import json
import os
import queue
import re
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request

# ------------------------------------------------------------------ 主题
BG      = "#FBFAF8"   # 页面底色
CARD    = "#FFFFFF"   # 卡片
INK     = "#2A2A28"   # 主文字
SUB     = "#8F8D87"   # 次级文字
FAINT   = "#B6B4AD"   # 占位符
LINE    = "#E7E5E0"   # 描边
ACCENT  = "#33322E"   # 主按钮
HOVER   = "#4A4843"
SOFT    = "#F3F2EE"   # 浅底
GOOD    = "#6E7F6A"
MID     = "#A99467"
LOW     = "#A8705F"

FAMILY = "Microsoft YaHei UI"


def F(size, weight="normal"):
    return (FAMILY, size, weight)


# ------------------------------------------------------------------ 小控件
def rr(cv, x1, y1, x2, y2, r, **kw):
    """圆角矩形"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class RButton(tk.Canvas):
    def __init__(self, parent, text, command=None, w=160, h=44, fill=ACCENT,
                 fg="#FFFFFF", outline=None, radius=10, bg=BG, size=11,
                 hover=None, weight="normal"):
        super().__init__(parent, width=w, height=h, bg=bg,
                         highlightthickness=0, bd=0)
        self._cmd = command
        self._fill = fill
        self._fg = fg
        self._hover = hover or (HOVER if fill == ACCENT else SOFT)
        self._outline = outline or fill
        self._enabled = True
        self.shape = rr(self, 1, 1, w - 1, h - 1, radius,
                        fill=fill, outline=self._outline, width=1)
        self.label = self.create_text(w / 2, h / 2, text=text, fill=fg,
                                      font=F(size, weight))
        self.configure(cursor="hand2")
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def _enter(self, _=None):
        if self._enabled:
            self.itemconfig(self.shape, fill=self._hover, outline=self._hover)

    def _leave(self, _=None):
        if self._enabled:
            self.itemconfig(self.shape, fill=self._fill, outline=self._outline)

    def _click(self, _=None):
        if self._enabled and self._cmd:
            self._cmd()

    def set_text(self, t):
        self.itemconfig(self.label, text=t)

    def set_style(self, fill, fg, outline=None, hover=None):
        """切换选中态：换填充、文字色与描边"""
        self._fill = fill
        self._fg = fg
        self._outline = outline or fill
        self._hover = hover or (HOVER if fill == ACCENT else SOFT)
        self.itemconfig(self.shape, fill=fill, outline=self._outline)
        self.itemconfig(self.label, fill=fg)

    def set_enabled(self, ok):
        """禁用态：变灰且点不动（请求进行中时用）"""
        self._enabled = ok
        self.configure(cursor="hand2" if ok else "arrow")
        self.itemconfig(self.shape,
                        fill=self._fill if ok else "#EDEBE6",
                        outline=self._outline if ok else LINE)
        self.itemconfig(self.label, fill=self._fg if ok else FAINT)


def set_text(w, s):
    w.configure(state="normal")
    w.delete("1.0", "end")
    w.insert("1.0", s)
    w.configure(state="disabled")


def card(parent, bg=CARD):
    f = tk.Frame(parent, bg=bg, highlightbackground=LINE,
                 highlightthickness=1, bd=0)
    return f


# ------------------------------------------------------------------ 关卡数据
def D(name, weight, signals=None, typ="signals", low="", high=""):
    return {"name": name, "weight": weight, "type": typ,
            "signals": signals or [], "low": low, "high": high}


TASKS = [
    {
        "title": "科普解释",
        "diff": 1,
        "bg": "你在一家青少年科普公众号做内容。主编说：最近要发一期「植物是怎么吃饭的」，"
              "你先写个提示词，让 AI 把「光合作用」讲给小学生听。",
        "task": "写一条提示词，让 AI 输出一段给小学三年级学生看的、150 字以内的光合作用解释。",
        "dims": [
            D("受众定位", 25,
              ["三年级", "小学生", "小学", "8岁", "九岁", "孩子", "儿童", "小朋友", "低龄"],
              low="你没说清这段文字写给谁看。受众是解释类写作的第一约束——「三年级学生」和「中学生」需要完全不同的语言。",
              high="受众交代得很明确，AI 知道该用什么语言密度。"),
            D("通俗化要求", 25,
              ["比喻", "打比方", "类比", "举例", "生活", "日常", "故事", "通俗", "简单",
               "不要用术语", "少用", "避免术语", "口语"],
              low="只说了「讲给小孩听」，但没说怎么做到通俗。加一句「用生活里的场景打比方」，效果差一大截。",
              high="主动给了通俗化的手法，AI 会有意识地去做转换。"),
            D("篇幅约束", 15,
              ["150字", "一百五十", "字数", "以内", "不超过", "控制在", "篇幅", "简短"],
              low="没有约束长度。不给字数，AI 默认会写长出好几倍。",
              high="长度约束明确，产出可控。"),
            D("准确性约束", 20,
              ["不要", "避免", "不能", "准确", "科学", "不要编造", "误区", "严谨", "错误"],
              low="科普最容易翻车的地方是「为了通俗而失真」。补一句「不要为了好懂而牺牲准确性／不要编造」，会安全很多。",
              high="注意到了通俗与准确的平衡，这是科普写作的关键。"),
            D("结构清晰", 15, typ="structural",
              low="整段话没有分点，AI 容易漏掉你的某一条要求。试着把要求列成 1) 2) 3)。",
              high="指令排列有条理，AI 不容易漏项。"),
        ],
        "model": "你是一位擅长给儿童讲科学的科普作家。请用小学三年级学生能听懂的语言，写一段解释「光合作用」的文字，"
                 "不超过 150 字。要求：\n"
                 "1) 用孩子熟悉的生活场景打比方（比如吃饭、做饭、晒太阳）；\n"
                 "2) 不要出现「叶绿体」「光反应」「暗反应」这类专业术语，必须出现时用大白话替代；\n"
                 "3) 先讲植物要「吃」什么，再讲它们怎么「吃」；\n"
                 "4) 不要为了好懂而编造不准确的说法；\n"
                 "5) 语气亲切，像在讲故事。\n"
                 "只输出这段话本身，不要标题、不要额外说明。",
        "tip": "解释类任务的核心矛盾是「好懂」与「准确」，好的提示词会同时把这两头都框住。",
    },
    {
        "title": "投诉回复",
        "diff": 2,
        "bg": "你在一家电商公司做客服主管。一位顾客投诉：下单的保温杯到货后杯盖拧不紧，"
              "而且物流比承诺时间晚了 3 天。她情绪很激动，要求给个说法。",
        "task": "写一条提示词，让 AI 起草一封回复邮件，安抚顾客并给出解决方案。",
        "dims": [
            D("角色与语气", 20,
              ["客服", "主管", "语气", "诚恳", "抱歉", "歉意", "安抚", "专业", "耐心", "不卑不亢"],
              low="没有设定角色和语气。AI 默认口吻偏机械，客服场景里语气本身就是业务能力。",
              high="给了角色和语气基准，回复的「人味」有了保证。"),
            D("事实要素", 25,
              ["保温杯", "杯盖", "拧不紧", "物流", "延迟", "3天", "三天", "晚", "两件事", "两个问题"],
              low="投诉里有两个独立问题（产品瑕疵 + 物流延误），你至少要确保 AI 两个都回。漏掉一个，顾客只会更火。",
              high="把顾客的具体情况交代清楚了，AI 不用凭空猜。"),
            D("解决方案", 20,
              ["补发", "换货", "退款", "退货", "补偿", "优惠券", "赔付", "运费", "48小时", "重发"],
              low="没有告诉 AI 能给什么方案。不指定方案，AI 只会写一堆「我们非常重视」，实际问题一个没解决。",
              high="给了具体可执行的补偿方案，回复才有落点。"),
            D("边界约束", 20,
              ["不要承诺", "避免承诺", "不得", "不可以", "超出权限", "谨慎", "不过度", "上报", "先核实", "不要推卸", "不找借口"],
              low="没有划边界。客服提示词必须写清「哪些话不能说／不能承诺」，否则 AI 很容易给出公司兑现不了的承诺。",
              high="给 AI 划了红线，这是企业场景里最容易被忽略、也最要命的一环。"),
            D("输出格式", 15,
              ["邮件", "主题", "称呼", "落款", "署名", "分段", "开头", "结尾", "格式"],
              low="没规定输出格式。你要的是「一封邮件」，就把邮件该有的部件说清楚。",
              high="格式交代清楚，拿到就能用。"),
        ],
        "model": "你是一名有 5 年经验的电商客服主管，语气真诚、专业、不卑不亢。请起草一封回复邮件，"
                 "回复一位顾客的投诉：她购买的保温杯到货后发现杯盖拧不紧，且物流比承诺时间晚了 3 天，她现在很生气。\n"
                 "要求：\n"
                 "1) 两个问题都要回应，不要只挑好处理的；开头真诚致歉，承认问题出在我们这边；\n"
                 "2) 不要找借口、不要推卸给物流方；\n"
                 "3) 给出具体方案：免费补发一个杯盖 + 赠 10 元无门槛券，并说明 48 小时内发出；\n"
                 "4) 不要承诺现金赔偿或其他超出客服权限的补偿，如顾客坚持，说明「将由主管跟进」；\n"
                 "5) 输出为一封完整邮件：含主题行、称呼、正文分段、客服署名；\n"
                 "6) 全文不超过 400 字，语气不要过度卑微。",
        "tip": "客服场景的评分重点不在文采，而在「问题全覆盖」和「不越权承诺」这两条看不见的红线。",
    },
    {
        "title": "写个函数",
        "diff": 3,
        "bg": "你在带一个新人写代码。他总说「AI 写的函数跑不了」，你想示范一次怎么把需求说清楚。",
        "task": "写一条提示词，让 AI 写出 Python 函数 is_valid_cn_mobile(s)，用于校验中国大陆手机号。",
        "dims": [
            D("功能规格", 25,
              ["手机号", "11位", "11 位", "1开头", "中国大陆", "正则", "13", "15", "18", "17", "19",
               "校验", "验证", "第二位"],
              low="功能只说了一半。手机号的校验规则（11 位、1 开头、第二位范围）不写清，AI 会按自己的理解编一套。",
              high="把判定规则交代明白了，AI 不用猜业务含义。"),
            D("输入输出定义", 20,
              ["输入", "输出", "返回", "参数", "bool", "布尔", "字符串", "类型", "str", "True", "False"],
              low="没定义入参和返回值类型。AI 可能返回字符串、可能抛异常，也可能打印结果——都不是你要的。",
              high="输入输出定义清晰，接口不会跑偏。"),
            D("边界与异常", 25,
              ["空", "None", "异常", "非字符串", "长度", "边界", "空格", "strip", "测试", "用例", "极端"],
              low="这是本题最容易失分的地方。只给「正常手机号」这一种情况，AI 写出的函数一遇到 None、空串、带空格的输入就崩。",
              high="主动覆盖了异常输入——这正是让 AI 写出的代码「真的能跑」的关键。"),
            D("代码要求", 15,
              ["Python", "函数", "命名", "注释", "类型注解", "文档", "docstring", "标准库", "第三方", "简洁", "re"],
              low="没提实现约束（是否可用第三方库、要不要注释）。不说，AI 就会自由发挥。",
              high="给出了实现层面的约束，产出的代码风格可控。"),
            D("结构清晰", 15, typ="structural",
              low="需求挤成一团。代码类需求尤其要分点，AI 才不会漏掉边界条件。",
              high="需求分点排列，实现要点一目了然。"),
        ],
        "model": "请用 Python 3 写一个函数 is_valid_cn_mobile(s)，校验字符串是否为中国大陆手机号，返回 bool。\n"
                 "要求：\n"
                 "1) 入参 s 为任意类型，若不是 str 直接返回 False，不要抛异常；\n"
                 "2) 允许前后有空格，先 strip 再判断；\n"
                 "3) 规则：11 位纯数字，以 1 开头，第二位为 3-9；\n"
                 "4) 使用 re 标准库实现，不引入任何第三方包；\n"
                 "5) 加类型注解和一行 docstring；\n"
                 "6) 附 5 个测试用例（合法号、位数不足、含字母、None、带空格），并标注每个的预期结果。\n"
                 "只输出代码和测试用例，不要解释原理。",
        "tip": "代码类提示词的关键差异点永远是「异常与边界」——这正是新手提示词最常漏的一条。",
    },
    {
        "title": "种草文案",
        "diff": 2,
        "bg": "你是一家新锐香氛品牌的内容运营。新品是一款「雨后青草味」香薰蜡烛，"
              "预算有限，第一波只能靠小红书自然流量。",
        "task": "写一条提示词，让 AI 产出一篇可以直接发布的小红书笔记。",
        "dims": [
            D("平台调性", 20,
              ["小红书", "笔记", "emoji", "表情", "标题", "标签", "第一人称", "真实", "分享", "种草", "口语"],
              low="没说明平台。一篇正儿八经的商品说明放到小红书，数据会很难看——平台调性要先立住。",
              high="锁定了平台语感，AI 知道该用什么腔调说话。"),
            D("人群与卖点", 25,
              ["人群", "女生", "独居", "租房", "上班族", "学生", "年龄", "卖点", "青草", "雨后", "气味", "场景", "卧室", "书房", "氛围"],
              low="「好闻」不是卖点。要告诉 AI：卖给谁、在什么场景用、和竞品比特别在哪。",
              high="人群与场景都点到了，文案才有具体的画面。"),
            D("字数与结构", 15,
              ["字", "标题", "正文", "标签", "分段", "结构", "以内", "开头", "结尾"],
              low="没给字数与结构。不给，AI 会按自己的习惯写，可能完全没有「标题 + 正文 + 话题」的小红书骨架。",
              high="字数与结构说清楚了，产出能直接用。"),
            D("平台禁忌", 20,
              ["不要", "避免", "广告法", "极限词", "最", "第一", "绝对", "功效", "治疗", "夸大", "违禁"],
              low="漏了这条会有真实风险：小红书对绝对化用语和功效宣称是限流甚至违规的。提示词里必须写明禁用词。",
              high="主动规避了平台与法规红线，这是专业运营和新手的分水岭。"),
            D("可执行细节", 20,
              ["钩子", "话题", "#", "互动", "提问", "评论", "结尾", "开头", "情绪", "共鸣"],
              low="没给具体的写作抓手。加上「开头要有钩子」「结尾带 3 个话题标签」这类细节，产出质量会明显不同。",
              high="给了可执行的写作细节，AI 不用自由发挥。"),
        ],
        "model": "你是小红书香氛赛道的资深内容运营。请为一款「雨后青草味」香薰蜡烛写一篇小红书种草笔记。\n"
                 "要求：\n"
                 "1) 目标人群：20-30 岁、独居租房、喜欢自然感的女生；\n"
                 "2) 标题 20 字以内，带 1-2 个 emoji，要有让人想点开的钩子；\n"
                 "3) 正文 200-300 字，第一人称真实分享口吻：先写使用场景（下班后 / 阴雨天 / 睡前），"
                 "再写气味感受（具体到「割草味」「潮湿泥土味」，不要只说「很清新」），最后落到性价比；\n"
                 "4) 严禁出现「最」「第一」「绝对」「助眠神器」「治疗」等绝对化与功效类词汇；\n"
                 "5) 结尾带 3 个针对这篇内容设计的话题标签；\n"
                 "6) 分段，每段不超过 3 行。\n"
                 "只输出笔记内容，不要解释你的思路。",
        "tip": "平台型写作任务里，评分权重会明显偏向「平台禁忌」——因为它是真实业务风险，不是文笔问题。",
    },
    {
        "title": "找数据异常",
        "diff": 3,
        "bg": "你在一家连锁咖啡公司做运营分析。市场部丢来一份数据：30 家门店、近 6 个月的销售明细，"
              "字段有日期、门店、品类、销量、客单价、天气。老板只问了一句：「有没有不对劲的地方？」",
        "task": "写一条提示词，让 AI 帮你从数据里找出「需要关注的异常及可能原因」。",
        "dims": [
            D("分析目标", 20,
              ["异常", "下滑", "波动", "原因", "关注", "问题", "排查", "找出", "为什么", "不对劲"],
              low="「分析一下」是无效指令。要说清你要的是「找异常」还是「看趋势」还是「给建议」，三者方法完全不同。",
              high="分析目标明确，AI 不会跑去做一份通用描述。"),
            D("方法要求", 25,
              ["同比", "环比", "趋势", "对比", "分组", "维度", "门店", "品类", "天气", "相关",
               "均值", "标准差", "阈值", "异常值", "时间段"],
              low="没指定分析路径。不给维度，AI 只能给一段含糊的概述——「有的店涨了，有的店跌了」。",
              high="指定了切入维度与量化方法，输出才有可验证的结论。"),
            D("输出格式", 20,
              ["表格", "格式", "分点", "结论", "优先级", "排序", "字段", "markdown", "列表"],
              low="没规定输出格式。分析类结果不落成表格或分点结论，基本没法给老板看。",
              high="规定了输出形态，结果可直接交付。"),
            D("严谨性约束", 20,
              ["不要编造", "不要推测", "区分", "推测", "假设", "数据不足", "需要补充", "验证", "置信", "只能"],
              low="这条很重要：AI 在数据分析里最容易「编出合理但不存在」的结论。必须要求它区分「数据支持的」和「它猜的」。",
              high="要求了结论与推测分离——这是数据分析提示词里最专业的写法。"),
            D("结构清晰", 15, typ="structural",
              low="指令没有分点。分析类任务的条件多，不分点几乎必然漏项。",
              high="指令结构清楚，AI 能逐条对齐执行。"),
        ],
        "model": "你是资深零售数据分析师。下面是一份某连锁咖啡品牌 30 家门店近 6 个月的销售明细"
                 "（字段：日期、门店、品类、销量、客单价、天气）。请分析并找出「需要关注的异常」。\n"
                 "要求：\n"
                 "1) 从三个维度切入：门店维度、品类维度、时间维度；\n"
                 "2) 每条异常都要量化：具体门店/品类、波动幅度、出现的时间段；\n"
                 "3) 结合天气字段做初步相关性判断，但必须明确区分「数据支持的结论」和「我的推测」；\n"
                 "4) 若数据不足以支撑结论，直接说明需要补充哪些数据；\n"
                 "5) 输出格式：Markdown 表格 + 分点结论，按影响程度从高到低排序；\n"
                 "6) 不要编造数据中不存在的字段或数字。\n"
                 "最后列出 3 个你最想问我的问题。",
        "tip": "分析类任务的评分重点会从「写得清不清楚」转向「会不会被 AI 带偏」，所以防幻觉的约束权重很高。",
    },
    {
        "title": "别越界的建议",
        "diff": 3,
        "bg": "你在维护一个健康科普助手。有用户留言：「我最近总是头晕，晚上睡不好，能不能吃点什么药？」"
              "——你知道这个问题，答得太满和答得太空都是失败。",
        "task": "写一条提示词，让 AI 的回复既有用、又守住安全边界。",
        "dims": [
            D("安全边界", 35,
              ["不要诊断", "不能诊断", "不替代", "医生", "处方", "用药", "药名", "免责", "风险", "个体差异", "仅供参考", "禁止"],
              low="本关权重最高的维度。医疗场景里，提示词不给「不许诊断、不许推荐药物」的硬约束，AI 很可能直接给出药名和剂量——这是真实风险。",
              high="把安全红线写进了提示词，这是这个场景的第一优先级。"),
            D("有用性", 20,
              ["可能", "原因", "建议", "作息", "记录", "症状", "何时", "观察", "生活方式", "诱因"],
              low="为了安全就写得空空如也，「建议您就医」是没价值的。要给可执行的通用信息，才会有用。",
              high="在安全前提下给出了可落地的信息，这才是「有用」。"),
            D("共情语气", 20,
              ["共情", "理解", "关心", "不安", "别着急", "温和", "耐心", "焦虑", "体谅"],
              low="用户带着不适和焦虑来提问，冷冰冰的免责声明会让人更难受。语气需要被写进提示词。",
              high="要求了共情语气，回复才不像免责公告。"),
            D("就医引导", 15,
              ["就医", "医院", "就诊", "科室", "神经内科", "耳鼻喉", "及时", "尽快", "线下", "危险信号"],
              low="没给「什么情况必须去医院」的判断标准。只说「建议就医」太笼统，用户不会当回事。",
              high="给了明确的就医信号和科室指引，引导才有实际作用。"),
            D("结构清晰", 10, typ="structural",
              low="这类回复需要分点，挤成一段用户根本读不下去。",
              high="结构清楚，符合科普场景的阅读习惯。"),
        ],
        "model": "你是一名健康科普助手，不是医生。请回复用户提问：「我最近总是头晕，晚上睡不好，能不能吃点什么药？」\n"
                 "要求：\n"
                 "1) 语气温和有共情，先承认他的不适感是真实的，不要一上来就免责；\n"
                 "2) 明确说明：我不能做诊断，也不能推荐具体药物或剂量，请勿自行用药；\n"
                 "3) 给出 3-4 条安全的通用生活建议：规律作息、睡前减少屏幕、记录头晕发生的时间与伴随症状、"
                 "留意血压与贫血等常见诱因，并说明这些都不是诊断；\n"
                 "4) 明确列出需要尽快就医的信号（天旋地转、视物模糊、言语不清、晕倒、伴胸痛），"
                 "并建议线下就诊科室（神经内科 / 耳鼻喉科）；\n"
                 "5) 分点输出，200-300 字，不要出现任何具体药名。",
        "tip": "同一个「怎么写提示词」的问题，在不同场景下评分权重可以相差很大——这就是自适应评分要解决的事。",
    },
    {
        "title": "写个开头",
        "diff": 2,
        "bg": "你是科幻杂志的编辑，正在做一期「未来记忆」主题的征稿。收到的来稿里，"
              "十篇有八篇开头都是「未来世界，科技高度发达」——你想先自己试写一条提示词。",
        "task": "写一条提示词，让 AI 写一段 300 字以内的微型小说开头。",
        "dims": [
            D("创意方向", 25,
              ["记忆", "未来", "设定", "概念", "前提", "科技", "上传", "移植", "删除", "租赁", "载体", "脑"],
              low="只说了「写个科幻开头」，没有给任何设定方向。宽泛的创意指令，得到的一定是最俗套的那个答案。",
              high="给了具体的设定前提，创意才有落点。"),
            D("风格与氛围", 25,
              ["风格", "氛围", "冷峻", "克制", "细腻", "第一人称", "视角", "节奏", "画面", "白描", "不抒情"],
              low="没指定风格。不说「克制还是浓烈」「第一人称还是第三人称」，出来的东西可能完全不是你要的调子。",
              high="风格与视角都指定了，语感可控。"),
            D("硬性约束", 20,
              ["300字", "以内", "字数", "开头", "一段", "悬念", "只输出", "不要标题"],
              low="没给长度和输出边界。不给，AI 会写成一整篇，还自带标题。",
              high="硬性约束清晰，拿到就能直接排版。"),
            D("禁忌与俗套", 20,
              ["不要", "避免", "陈词滥调", "俗套", "禁用", "不要写", "烂", "套话"],
              low="创意类提示词最有效的一招就是「明确排除俗套」。你不排除，AI 一定会给你「科技高度发达」那一套。",
              high="主动排除俗套，这是写创意提示词的高阶技巧。"),
            D("结构清晰", 10, typ="structural",
              low="要求没有分点，创作类的多重约束很容易被漏掉。",
              high="条目清楚，约束容易被完整执行。"),
        ],
        "model": "你是一位冷峻克制的华语科幻作家。请为「未来记忆」主题写一段 300 字以内的微型小说开头。\n"
                 "要求：\n"
                 "1) 核心设定必须包含一项具体的记忆技术（例如记忆可以租赁、被明码标价、可被删除），"
                 "在叙述中自然带出，不要解释设定；\n"
                 "2) 第一人称，冷色调，白描为主，不抒情、不感叹；\n"
                 "3) 第一句就要有钩子，让读者想读第二句；\n"
                 "4) 结尾留悬念，不要给出解释；\n"
                 "5) 禁止出现「记忆的海洋」「数据的洪流」「他到底是谁」这类陈词滥调；"
                 "禁止用「未来世界，科技高度发达」开头；\n"
                 "6) 只输出小说片段，不要标题、不要任何说明。",
        "tip": "创意类任务里，「排除什么」往往比「要什么」更能决定产出质量。",
    },
    {
        "title": "模拟面试",
        "diff": 3,
        "bg": "你要准备产品经理岗的面试，想先找个陪练。问题是：AI 如果一口气把 8 个问题全列出来，"
              "这场模拟就废了。",
        "task": "写一条提示词，设定 AI 的角色与规则，让它能连续多轮提问并给出反馈。",
        "dims": [
            D("角色设定", 20,
              ["面试官", "角色", "资深", "产品经理", "面试", "大厂", "扮演", "你是一个", "你是"],
              low="没设定角色。AI 会以助手的口吻给你建议，而不是「面试官」的身份来考你——模拟感就没了。",
              high="角色立住了，交互的基调就定了。"),
            D("规则与流程", 30,
              ["一轮", "一个问题", "流程", "顺序", "第一轮", "追问", "多轮", "结束", "难度", "递进", "共"],
              low="本关权重最高的一项。多轮交互类提示词，核心就是「流程规则」：一次问几道、按什么顺序、难度怎么递进。不写这些，AI 只会一口气刷完所有问题。",
              high="把交互流程写清楚了，这才能真的「多轮」起来。"),
            D("反馈机制", 20,
              ["反馈", "点评", "评价", "打分", "评分", "建议", "复盘", "亮点", "不足", "改进"],
              low="没要求反馈。那 AI 就只会一直问，你练完了也不知道自己哪里答得差。",
              high="定义了反馈机制，练习才有闭环。"),
            D("交互约束", 15,
              ["一次", "不要连续", "等我", "回答后", "每次只", "不要替", "结束条件", "多少题", "8题", "八题"],
              low="没有「等我回答后再问下一题」这类约束，AI 很可能一口气抛出全部问题。",
              high="交互节奏被约束住了，不会一次刷完。"),
            D("结构清晰", 15, typ="structural",
              low="规则没有分点。多轮规则只要有一条没被 AI 读到，整个模拟就跑偏。",
              high="规则分点排列，逐条可执行。"),
        ],
        "model": "请你扮演一位大厂资深产品经理面试官，我是应聘产品经理岗位的候选人。\n"
                 "规则：\n"
                 "1) 一次只问一个问题，必须等我回答后再问下一个，不要连续提问；\n"
                 "2) 共 8 轮，按「自我介绍 → 产品感 → 数据分析 → 项目经历 → 反问」的顺序递进，"
                 "从第 5 轮起加大追问力度；\n"
                 "3) 每轮在我回答后，先用一句话给出即时反馈（指出一个亮点或一个漏洞），再进入下一题；\n"
                 "4) 不要替我回答问题，不要一次抛出多个问题；\n"
                 "5) 8 轮结束后给我一份复盘：整体评分（1-5 分）、3 个亮点、3 个待改进点、1 条最关键的提升建议；\n"
                 "6) 全程用中文，语气专业但不过分压迫。\n"
                 "现在开始第一轮。",
        "tip": "凡是牵涉「多轮交互」的任务，评分权重都会大幅偏向流程规则——因为那才是决定成败的地方。",
    },
]

# ------------------------------------------------------------------ 简单模式辅助内容
# 写作提示：{关卡下标: {维度名: 怎么写}}，与 TASKS[i]["dims"] 一一对应。
# 只给「该想什么」的方向，不直接给信号词，避免变成照抄答案。
HINTS = {
    0: {
        "受众定位": "先写下这段文字给谁看：大概几年级、多大、已经知道多少。",
        "通俗化要求": "说清「怎么做到通俗」——用什么手法把概念换成人能想象的东西。",
        "篇幅约束": "给一个明确的字数上限，不然 AI 会写长好几倍。",
        "准确性约束": "补一句限制，防止它为了好懂而讲错。",
        "结构清晰": "把要求逐条编号列出来，别挤成一大段。",
    },
    1: {
        "角色与语气": "先给 AI 一个身份（干什么的、几年经验）和该有的语气基调。",
        "事实要素": "数一下顾客提了几个问题，逐个写进提示词，要求都回应。",
        "解决方案": "写明你能给的具体补偿动作和时间点，别让 AI 自己编方案。",
        "边界约束": "划出红线：哪些话不能说、哪些事不能承诺。",
        "输出格式": "说清要输出的是一封邮件，以及邮件该有哪些部件。",
    },
    2: {
        "功能规格": "把「什么算合法手机号」的判定规则逐条写出来。",
        "输入输出定义": "写明入参是什么类型、返回值是什么类型。",
        "边界与异常": "先想「什么样的输入会让函数崩」，再要求 AI 处理它们。",
        "代码要求": "规定能不能用第三方库、要不要注释和类型注解。",
        "结构清晰": "需求分点列——代码类需求漏一条就少一个分支。",
    },
    3: {
        "平台调性": "先说明发在哪个平台，以及这个平台上的人平时怎么说话。",
        "人群与卖点": "写清卖给谁、在什么场景用、和同类产品比特别在哪。",
        "字数与结构": "给标题字数、正文字数，以及「标题 + 正文 + 标签」的骨架。",
        "平台禁忌": "列出不许出现的词：绝对化用语、功效类宣称。",
        "可执行细节": "补上开头钩子、结尾互动这类具体的写作抓手。",
    },
    4: {
        "分析目标": "明确你要的是「找异常」、还是「看趋势」、还是「给建议」。",
        "方法要求": "指定从哪几个维度切进去、用什么方法做比较。",
        "输出格式": "规定结果怎么呈现：表格、排序、还是分点结论。",
        "严谨性约束": "要求它把「数据支持的结论」和「自己的推测」分开写。",
        "结构清晰": "条件多，必须分点，否则 AI 一定会漏。",
    },
    5: {
        "安全边界": "把不许做的事写死：不做诊断、不推荐具体药物和剂量。",
        "有用性": "补充可执行的通用建议，别只写一句「请及时就医」。",
        "共情语气": "要求先接住对方的情绪，再讲内容。",
        "就医引导": "给出「什么情况必须去医院」的判断信号和对应科室。",
        "结构清晰": "分点写，用户才读得下去。",
    },
    6: {
        "创意方向": "给一个具体的设定前提，别只说「写个科幻开头」。",
        "风格与氛围": "指定语感（冷峻还是浓烈）和叙述视角（第一人称还是第三人称）。",
        "硬性约束": "限字数上限，并说清输出边界、要不要标题。",
        "禁忌与俗套": "明确排除你不想看到的套路写法。",
        "结构清晰": "多重约束要分点，创作类最容易漏掉一条。",
    },
    7: {
        "角色设定": "先立住 AI 的身份，多轮交互的基调才定得下来。",
        "规则与流程": "写清一轮几道题、按什么顺序、难度怎么递进。",
        "反馈机制": "要求每轮给即时反馈，并在最后给一份复盘。",
        "交互约束": "加一条「等我回答完再问下一题」。",
        "结构清晰": "规则分点排列，漏一条整个流程就跑偏。",
    },
}

# 写作模板：把【】里的空补掉即可，是本关维度的骨架，不是标准答案。
TEMPLATES = {
    0: "你是一位【角色：擅长给谁讲什么的人】。\n"
       "请用【受众：几年级 / 多大 / 什么基础】能听懂的语言，写一段解释【主题】的文字，不超过【字数】字。\n"
       "要求：\n"
       "1) 用【什么手法】把概念讲通俗，比如【举个具体的比方方向】；\n"
       "2) 不要出现【要避免的术语或写法】；\n"
       "3) 先讲【什么】，再讲【什么】；\n"
       "4) 不要为了好懂而【要防的这种错误】；\n"
       "5) 语气【语气要求】。\n"
       "只输出这段话本身，不要标题、不要额外说明。",
    1: "你是一名【角色：什么岗位、几年经验】，语气【语气基调】。\n"
       "请起草一封回复邮件，回复一位顾客的投诉：【把顾客的问题逐条写出来】。\n"
       "要求：\n"
       "1) 【共有几个问题】都要回应，不要只挑好处理的；\n"
       "2) 不要【不该说的话，例如找借口、推卸责任】；\n"
       "3) 给出具体方案：【你能给的动作 + 时间点】；\n"
       "4) 不要承诺【超出你权限的补偿】，如顾客坚持，就【该怎么处理】；\n"
       "5) 输出为一封完整邮件，包含【邮件该有的部件】；\n"
       "6) 全文不超过【字数】字。",
    2: "请用【语言 / 版本】写一个函数【函数名(参数)】，功能是【做什么】，返回【类型】。\n"
       "要求：\n"
       "1) 入参为【什么类型之外】时，返回【什么】，不要抛异常；\n"
       "2) 【输入预处理，例如去空格】；\n"
       "3) 判定规则：【逐条写出规则】；\n"
       "4) 使用【允许的库】实现，不引入【禁止的依赖】；\n"
       "5) 加上【注释 / 类型注解 / 文档】；\n"
       "6) 附【几个】测试用例，覆盖【正常情况 + 哪几类异常】，并标注预期结果。\n"
       "只输出代码和测试用例，不要解释原理。",
    3: "你是【平台 + 赛道】的资深运营。请为【产品】写一篇【平台】笔记。\n"
       "要求：\n"
       "1) 目标人群：【年龄 / 身份 / 生活方式】；\n"
       "2) 标题【字数】以内，带【几个】emoji，要有【钩子类型】；\n"
       "3) 正文【字数区间】，用【人称 / 口吻】，先写【场景】，再写【感受或卖点】，最后落到【落脚点】；\n"
       "4) 严禁出现【违禁词方向】这类词汇；\n"
       "5) 结尾带【几个】【什么类型】的话题标签；\n"
       "6) 【分段或排版要求】。\n"
       "只输出笔记内容，不要解释你的思路。",
    4: "你是资深【行业】数据分析师。下面是一份【数据说明：规模、时间跨度、字段】。\n"
       "请分析并找出【你要的目标】。\n"
       "要求：\n"
       "1) 从【几个】维度切入：【维度列表】；\n"
       "2) 每条结论都要量化：【门店 / 品类、波动幅度、时间段】；\n"
       "3) 【结合哪个字段】做初步判断，并明确区分「数据支持的结论」和「我的推测」；\n"
       "4) 若数据不足以支撑结论，直接说明需要补充哪些数据；\n"
       "5) 输出格式：【表格 / 分点 / 排序规则】；\n"
       "6) 不要编造【不能编的东西】。\n"
       "最后列出【几个】你最想问我的问题。",
    5: "你是一名【身份】，不是【不能被替代的角色】。请回复用户提问：「【用户原话】」。\n"
       "要求：\n"
       "1) 语气【情绪要求】，先【共情动作】，不要一上来就免责；\n"
       "2) 明确说明：我不能【禁止做的事】；\n"
       "3) 给出【几条】安全的通用建议：【建议方向】，并说明这些都不是诊断；\n"
       "4) 列出需要尽快就医的信号：【具体信号】，并建议【科室或就医方式】；\n"
       "5) 分点输出，【字数】，不要出现【禁止出现的内容】。",
    6: "你是【风格】的【领域】作家。请为【主题】写一段【字数】以内的【体裁】。\n"
       "要求：\n"
       "1) 核心设定必须包含【具体设定】，在叙述中自然带出，不要解释设定；\n"
       "2) 【人称 / 视角】，【文字风格】；\n"
       "3) 第一句【钩子要求】；\n"
       "4) 结尾【悬念或收束要求】；\n"
       "5) 禁止出现【要排除的俗套写法】；\n"
       "6) 只输出【什么】，不要【什么】。",
    7: "请你扮演【角色】，我是【你的身份】。\n"
       "规则：\n"
       "1) 一次只问【几个】问题，必须【交互节奏约束】；\n"
       "2) 共【几】轮，按【什么顺序】递进，从第【几】轮起【难度如何变化】；\n"
       "3) 每轮在我回答后，先【反馈要求】，再进入下一题；\n"
       "4) 不要【禁止的行为】；\n"
       "5) 结束后给我一份复盘，包含【复盘要素清单】；\n"
       "6) 【语言和语气要求】。\n"
       "现在开始第一轮。",
}

VERDICT = {
    "S": "这条提示词可以直接拿去用了——要素齐全、边界清晰，AI 几乎没有自由发挥的空间。",
    "A": "很扎实。任务、受众、约束基本交代清楚，再补一两个边界条件就是满分级。",
    "B": "方向对了，但还有几处会让 AI 自己「猜」的地方，补上就能明显提分。",
    "C": "AI 能勉强开工，但会大量依赖默认假设，产出大概率不是你想要的。",
    "D": "这条提示词还不足以驱动 AI 完成任务。先想清楚：要它做什么、给谁、什么形式。",
}

VAGUE = ["随便写", "随便", "都行", "都可以", "看着办", "你懂的", "帮我写一下",
         "写得好一点", "写好一点", "好一些", "越多越好", "尽量好"]


# ------------------------------------------------------------------ 评分引擎
_WS = re.compile(r"[\s\u3000]+")


def _norm(s):
    """去掉所有空白，避免「150 字」这类写法漏匹配"""
    return _WS.sub("", s)


def _hits(text, words, _cache={}):
    key = text
    n = _cache.get(key) if len(_cache) < 64 else None
    if n is None:
        n = _norm(text)
        if len(_cache) < 64:
            _cache[key] = n
    out = [w for w in words if _norm(w) in n]
    # 去掉被更长命中项包含的重复词（如「随便」与「随便写」）
    return [w for w in out if not any(w != o and w in o for o in out)]


def structural_score(text):
    s = 0
    if "\n" in text:
        s += 22
    bullets = len(re.findall(
        r"(?m)^\s*(?:[-*•·]|\d+[\.、)）]|\(?[一二三四五六七八九十]+[、.)）])", text))
    s += min(38, bullets * 13)
    n = len(text.strip())
    if n >= 100:
        s += 10
    if n >= 220:
        s += 8
    if re.search(r"要求|规则|格式|必须|禁止|注意|约束|输出", text):
        s += 14
    if len(re.findall(r"\d", text)) >= 3:
        s += 8
    return min(100, s)


def signal_score(text, dim):
    hits = _hits(text, dim["signals"])
    k = len(hits)
    sc = min(100, 50 + 23 * (k - 1)) if k else 0
    return sc, hits


def evaluate(task, prompt):
    text = (prompt or "").strip()
    dims = []
    for d in task["dims"]:
        if d["type"] == "structural":
            sc, hits = structural_score(text), []
        else:
            sc, hits = signal_score(text, d)
        dims.append({"name": d["name"], "weight": d["weight"], "score": sc,
                     "hits": hits, "low": d["low"], "high": d["high"],
                     "type": d["type"]})

    total = sum(x["weight"] * x["score"] for x in dims) / 100.0

    notes = []
    vague = _hits(text, VAGUE)
    total -= 6 * len(vague)

    n = len(text)
    if n < 15:
        total = min(total, 10.0)
        notes.append("提示词几乎只有一句话。任务目标、受众、输出形式都没交代，AI 只能猜。")
    elif n < 40:
        total = min(total, 55.0)
        notes.append("整体偏短。把「要什么、给谁看、什么形式、有什么限制」补全，分数会立刻不一样。")

    if vague:
        notes.append("出现了「" + "」「".join(vague) + "」这类模糊表达——AI 只能自由发挥，结果不可控。")

    total = max(0, min(100, int(round(total))))
    grade = ("S" if total >= 92 else "A" if total >= 82 else
             "B" if total >= 70 else "C" if total >= 58 else "D")
    return {"total": total, "grade": grade, "dims": dims,
            "notes": notes, "length": n}


def build_feedback(task, res):
    """生成本关反馈：优点 / 待改进"""
    good, weak = [], []
    for d in res["dims"]:
        if d["score"] >= 85 and d["high"]:
            good.append((d["weight"] * d["score"], "「%s」%s" % (d["name"], d["high"])))
        elif d["score"] < 72:
            weak.append((d["weight"] * (100 - d["score"]),
                         "「%s」%s" % (d["name"], d["low"])))
    good.sort(key=lambda x: -x[0])
    weak.sort(key=lambda x: -x[0])
    return [g[1] for g in good[:3]], [w[1] for w in weak[:3]]


# ------------------------------------------------------------------ AI 评分（可选）
# 玩家在开始页填入 DeepSeek API Key 后，可改由模型逐维度评审。
# 接口遵循 DeepSeek 的 OpenAI 兼容格式。刻意关掉思考模式：开着要多等几十秒，
# 游戏体感优先；而且思考模式下 temperature 不生效，关掉后评分反而更稳定。
AI_URL        = "https://api.deepseek.com/chat/completions"
AI_MODEL      = "deepseek-flash"
AI_TIMEOUT    = 60
AI_MAX_TOKENS = 2000
AI_THINKING   = False
CONF_PATH     = os.path.join(os.path.expanduser("~"), ".prompt_game.json")


def load_conf():
    try:
        with open(CONF_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_conf(d):
    try:
        with open(CONF_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


AI_SYSTEM = (
    "你是一位严格的提示词评审。玩家在玩一个「写提示词」的游戏：他要写一条提示词，"
    "交给 AI 去完成给定任务。你要判断这条提示词能否真的驱动 AI 把这件事做好。\n"
    "\n"
    "评分原则：\n"
    "1. 只按给定维度打分，不得增删维度、不得改动维度名，name 必须与给定维度名完全一致。\n"
    "2. score 为 0-100 的整数，要敢拉开差距：明确照顾到 = 80-100；提到但含糊 = 55-79；"
    "只沾一点边 = 30-54；完全没提 = 0-29。\n"
    "3. comment 必须具体，说清玩家写了什么、漏了什么、漏掉会导致什么后果；"
    "禁止空泛评语（如「写得不错」）；控制在 30-70 字。\n"
    "4. 空话、套话、模棱两可（如「认真完成」「写得好一点」）应当明显扣分。\n"
    "5. 不要因为提示词短就一律给低分——短而精准同样应该得高分。\n"
    "\n"
    "只输出合法 json，不要任何额外文字，格式如下：\n"
    '{"dims": [{"name": "维度名", "score": 0, "comment": "点评"}], '
    '"good": ["做得好的一点"], "weak": ["可以改进的一点"], "verdict": "总评"}\n'
    "其中 dims 覆盖全部给定维度且顺序一致；good 给 2-3 条，weak 给 2-3 条；"
    "verdict 为 30-60 字总评。"
)


def build_judge_prompt(task, prompt):
    """拼出评审用的 system / user 提示词"""
    dims = "\n".join("- %s（权重 %d%%）" % (d["name"], d["weight"])
                     for d in task["dims"])
    user = (
        "【任务背景】\n%s\n\n"
        "【具体任务】\n%s\n\n"
        "【本关评分维度与权重】\n%s\n\n"
        "【玩家写的提示词】\n\"\"\"\n%s\n\"\"\"\n\n"
        "请逐维度打分，并按约定输出 json。" % (task["bg"], task["task"], dims, prompt)
    )
    return AI_SYSTEM, user


def _clip(txt, n):
    return str(txt or "").strip().replace("\n", " ")[:n]


def _as_list(v, n, width=120):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    return [_clip(x, width) for x in v if str(x).strip()][:n]


def _extract_json(s):
    """模型偶尔会包一层 ```json 围栏或前后带解释文字，这里剥出来"""
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


def norm_ai_result(task, obj):
    """把模型返回的 json 规整成与本地评分一致的结构，缺失/越界一律兜底"""
    raw = [x for x in (obj.get("dims") or []) if isinstance(x, dict)]
    by = {}
    for x in raw:
        k = str(x.get("name", "")).strip()
        if k and k not in by:
            by[k] = x

    dims, weighted = [], 0.0
    for i, d in enumerate(task["dims"]):
        item = by.get(d["name"])
        if item is None and i < len(raw):     # 模型改动了维度名，按顺序兜底
            item = raw[i]
        item = item or {}
        try:
            sc = int(round(float(item.get("score", 0))))
        except Exception:
            sc = 0
        sc = max(0, min(100, sc))
        dims.append({"name": d["name"], "weight": d["weight"], "score": sc,
                     "hits": [], "low": d["low"], "high": d["high"],
                     "type": d["type"], "comment": _clip(item.get("comment"), 150)})
        weighted += d["weight"] * sc

    total = max(0, min(100, int(round(weighted / 100.0))))
    grade = ("S" if total >= 92 else "A" if total >= 82 else
             "B" if total >= 70 else "C" if total >= 58 else "D")
    return {"total": total, "grade": grade, "dims": dims, "notes": [],
            "length": 0, "good": _as_list(obj.get("good"), 3),
            "weak": _as_list(obj.get("weak"), 3),
            "verdict": _clip(obj.get("verdict"), 200) or VERDICT[grade],
            "ai": True}


def ai_score(api_key, task, prompt):
    """调用 DeepSeek 评审。成功返回 (res, None)，失败返回 (None, 错误说明)"""
    sys_p, usr_p = build_judge_prompt(task, prompt)
    body = {
        "model": AI_MODEL,
        "messages": [{"role": "system", "content": sys_p},
                     {"role": "user", "content": usr_p}],
        "response_format": {"type": "json_object"},
        "max_tokens": AI_MAX_TOKENS,
        "stream": False,
        "thinking": {"type": "enabled" if AI_THINKING else "disabled"},
    }
    if not AI_THINKING:
        body["temperature"] = 0.3
    req = urllib.request.Request(
        AI_URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + (api_key or "").strip()},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        msg = ""
        try:
            j = json.loads(e.read().decode("utf-8", "replace"))
            msg = (j.get("error") or {}).get("message") or ""
        except Exception:
            pass
        if e.code == 401:
            return None, "API Key 无效"
        if e.code == 402:
            return None, "账户余额不足"
        if e.code == 429:
            return None, "请求过于频繁"
        return None, "HTTP %d %s" % (e.code, _clip(msg, 90))
    except urllib.error.URLError as e:
        return None, "网络不通（%s）" % _clip(getattr(e, "reason", e), 50)
    except Exception as e:
        return None, _clip(e, 110)

    try:
        content = json.loads(raw)["choices"][0]["message"]["content"]
    except Exception:
        return None, "响应格式异常"
    if not (content or "").strip():
        return None, "模型返回了空内容"      # 官方说明 JSON 模式偶发空 content
    try:
        obj = _extract_json(content)
    except Exception:
        return None, "模型未按 json 格式返回"
    if not isinstance(obj, dict) or not obj.get("dims"):
        return None, "模型未返回评分维度"
    return norm_ai_result(task, obj), None


# ------------------------------------------------------------------ 主程序
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()            # 先藏起来量尺寸，避免启动瞬间窗口跳动/闪动
        self.title("PROMPT")
        self.configure(bg=BG)
        self.geometry("1060x780")
        self.minsize(880, 600)
        self.family = self._pick_font()

        self.idx = 0
        self.mode = "easy"         # easy 简单模式 / hard 困难模式
        self.scores = {}           # {关卡下标: 得分}，可跳关、可重写

        # AI 评分（可选）：Key 与开关都存在本机配置文件里
        conf = load_conf()
        self.api_key = str(conf.get("api_key") or "").strip()
        self.use_ai = bool(conf.get("use_ai", True)) and bool(self.api_key)
        self.ent_key = None        # 当前用于提交的 Key 输入框
        self._key_entries = []     # 所有 Key 输入框（开始页与设置弹窗同步用）
        self._key_eyes = []        # (输入框, 显示/隐藏按钮)
        self._key_shown = False
        self._ai_q = queue.Queue()
        self._ai_busy = False
        self._ai_t0 = 0.0
        self._ai_dots = 0

        self._max_w = 0            # 见过的最大内容尺寸，窗口只长不缩
        self._max_h = 0

        # 输入框行数随屏幕高度伸缩：关卡页在 150% 缩放下需要 1029px，
        # 屏幕不够高时若不降行数，底部「提交评分」会被挤出屏幕
        budget = self.winfo_screenheight() - 130
        self._ih = 10 if budget >= 1040 else 8 if budget >= 990 else 6
        self.container = tk.Frame(self, bg=BG)
        self.container.pack(fill="both", expand=True)

        self.frames = {}
        for name, builder in (("start", self._build_start),
                              ("select", self._build_select),
                              ("level", self._build_level),
                              ("result", self._build_result),
                              ("end", self._build_end)):
            fr = tk.Frame(self.container, bg=BG)
            self.frames[name] = fr
            builder(fr)
        self.show("start")
        self._measure_all()
        self._autosize()
        self.deiconify()

    def _measure_all(self):
        """启动时把所有关卡（简单模式最费空间，困难模式是其子集）与评分页都渲染
        一遍，量出最大内容尺寸。此后窗口固定，页面切换时不会忽高忽低。"""
        keep_mode, keep_idx = self.mode, self.idx
        keep_scores = dict(self.scores)

        # 开始页用 place 居中，尺寸不参与父容器计算，这里单独量一次
        self.update_idletasks()
        self._max_w = max(self._max_w, self._start_inner.winfo_reqwidth() + 120)
        self._max_h = max(self._max_h, self._start_inner.winfo_reqheight() + 110)

        self.mode = "easy"
        for i in range(len(TASKS)):
            self.idx = i
            self.load_level()
            self.update_idletasks()
            self._note("level")

        self.idx = 0
        t = TASKS[0]
        res = evaluate(t, t["model"])
        good, weak = build_feedback(t, res)
        self.render_result(t, res, good, weak, prompt=t["model"])
        self.update_idletasks()
        self._note("result")

        self.mode, self.idx, self.scores = keep_mode, keep_idx, keep_scores
        self.load_level()
        self.render_select()
        self.render_end()
        self.update_idletasks()
        self._note("select")
        self._note("end")

    def _note(self, name):
        """记录某页所需尺寸的峰值"""
        fr = self.frames[name]
        self._max_w = max(self._max_w, fr.winfo_reqwidth())
        self._max_h = max(self._max_h, fr.winfo_reqheight())

    def _autosize(self):
        """按内容实际所需尺寸 + 系统缩放设定窗口大小，避免高 DPI 下内容被裁掉"""
        self.update_idletasks()
        need_w = max(f.winfo_reqwidth() for f in self.frames.values())
        need_h = max(f.winfo_reqheight() for f in self.frames.values())
        self._max_w = max(self._max_w, need_w)
        self._max_h = max(self._max_h, need_h)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(max(self._max_w + 8, 1020), max(880, sw - 60))
        h = min(max(self._max_h + 8, 660), max(600, sh - 120))
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2),
                                       max(0, (sh - h) // 2 - 30)))

    # -------------------------------------------------- 基础设施
    def _pick_font(self):
        global FAMILY
        try:
            import tkinter.font as tkfont
            fams = set(tkfont.families(self))
            for cand in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
                         "PingFang SC", "SimHei"):
                if cand in fams:
                    FAMILY = cand
                    return cand
        except Exception:
            pass
        return FAMILY

    def show(self, name):
        for fr in self.frames.values():
            fr.pack_forget()
        self.frames[name].pack(fill="both", expand=True)

    def _pad(self, parent, x=44, y=30):
        f = tk.Frame(parent, bg=BG)
        f.pack(fill="both", expand=True, padx=x, pady=y)
        return f

    # -------------------------------------------------- 开始页
    def _build_start(self, root):
        box = self._pad(root, 0, 0)
        inner = tk.Frame(box, bg=BG)
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self._start_inner = inner

        tk.Label(inner, text="PROMPT", bg=BG, fg=INK,
                 font=F(52, "bold")).pack()
        tk.Label(inner, text="写一条好提示词，让 AI 真正听懂你", bg=BG, fg=SUB,
                 font=F(13)).pack(pady=(6, 30))

        tk.Frame(inner, bg=LINE, height=1, width=520).pack(pady=(0, 26))

        rules = [
            ("任务", "每一关给你一个真实场景和一项具体任务"),
            ("作答", "你写一条提示词，交给 AI 去完成它"),
            ("评分", "评分维度与权重随任务场景变化，不是一套固定规则"),
            ("建议", "分数不是目的，反馈才是——看看 AI 到底「听漏」了什么"),
        ]
        grid = tk.Frame(inner, bg=BG)
        grid.pack()
        for k, v in rules:
            row = tk.Frame(grid, bg=BG)
            row.pack(anchor="w", pady=5)
            tk.Label(row, text=k, bg=BG, fg=FAINT, font=F(10, "bold"),
                     width=4, anchor="w").pack(side="left")
            tk.Label(row, text=v, bg=BG, fg=INK, font=F(11)).pack(side="left")

        tk.Label(inner, text="共 8 关 · 简单 / 困难两种模式 · 不填 Key 也能离线玩",
                 bg=BG, fg=FAINT, font=F(10)).pack(pady=(26, 18))

        # ---- 可选：用模型来评分 ----
        tk.Frame(inner, bg=LINE, height=1, width=520).pack(pady=(0, 18))
        tk.Label(inner, text="可选 DeepSeek API：", bg=BG, fg=INK,
                 font=F(10, "bold"), anchor="w").pack(fill="x", pady=(0, 8))
        self.ent_key_start = self._key_widgets(inner)
        tk.Label(inner, text="填入后由 DeepSeek 逐维度点评（需联网，约 5–15 秒）\n"
                             "留空则用内置规则评分。Key 只保存在本机。",
                 bg=BG, fg=FAINT, font=F(9), anchor="w", justify="left").pack(fill="x",
                                                                             pady=(9, 0))

        RButton(inner, "开始", self.open_select, w=190, h=48, size=12).pack(pady=(24, 0))

    # -------------------------------------------------- 可选：AI 评分设置
    def _key_widgets(self, parent):
        """API Key 输入行：掩码输入 + 显示/隐藏 + 清除。
        开始页与设置弹窗共用同一套控件，内容双向同步。"""
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x")
        clr = RButton(row, "清除", self.clear_key, w=62, h=36, bg=BG, size=10,
                      fill=CARD, fg=SUB, outline=LINE)
        clr.pack(side="right", padx=(8, 0))
        eye = RButton(row, "显示", self.toggle_key_view, w=62, h=36, bg=BG, size=10,
                      fill=CARD, fg=SUB, outline=LINE)
        eye.pack(side="right", padx=(8, 0))

        box = tk.Frame(row, bg=CARD, highlightbackground=LINE,
                       highlightthickness=1, bd=0)
        box.pack(side="left", fill="x", expand=True)
        ent = tk.Entry(box, width=1, font=F(10), relief="flat", bg=CARD, fg=INK,
                       insertbackground=INK, highlightthickness=0,
                       show="" if self._key_shown else "•")
        ent.pack(fill="x", padx=12, pady=10)
        if self.api_key:
            ent.insert(0, self.api_key)
        ent.bind("<FocusOut>", lambda e: self._commit_key(ent))
        ent.bind("<Return>", lambda e: self._commit_key(ent))

        self._key_entries.append(ent)
        self._key_eyes.append((ent, eye))
        return ent

    def _sync_key(self):
        """把改动同步到所有 Key 输入框"""
        for e in self._key_entries:
            try:
                if e.winfo_exists() and e.get() != self.api_key:
                    e.delete(0, "end")
                    if self.api_key:
                        e.insert(0, self.api_key)
            except Exception:
                pass

    def _commit_key(self, ent=None):
        if ent is not None:
            self.ent_key = ent
        e = self.ent_key
        if e is None:
            return
        try:
            if not e.winfo_exists():
                return
            v = e.get()
        except Exception:
            return
        self.set_key(v)

    def set_key(self, v, use_ai=None):
        """设置 Key：写入配置、同步界面。清空即视为关闭 AI 评分"""
        v = (v or "").strip()
        if v == self.api_key and (use_ai is None or bool(use_ai) == self.use_ai):
            return
        had = bool(self.api_key)
        self.api_key = v
        if not v:
            self.use_ai = False
        elif use_ai is not None:
            self.use_ai = bool(use_ai)
        elif not had:
            self.use_ai = True          # 首次填入 Key，默认就启用
        self._sync_key()
        save_conf({"api_key": self.api_key, "use_ai": self.use_ai})
        self.render_engine()

    def clear_key(self):
        self.set_key("")

    def toggle_key_view(self):
        self._key_shown = not self._key_shown
        for ent, btn in self._key_eyes:
            try:
                if ent.winfo_exists():
                    ent.configure(show="" if self._key_shown else "•")
                if btn.winfo_exists():
                    btn.set_text("隐藏" if self._key_shown else "显示")
            except Exception:
                pass

    def ai_on(self):
        return bool(self.api_key) and bool(self.use_ai)

    def set_engine(self, m):
        if m == "ai" and not self.api_key:
            self.open_key_dialog()      # 没 Key 就引导去填
            return
        self.use_ai = bool(self.api_key) if m == "ai" else False
        save_conf({"api_key": self.api_key, "use_ai": self.use_ai})
        self.render_engine()

    def render_engine(self):
        """刷新选关页的「评分引擎」开关与说明"""
        on = self.ai_on()
        if on:
            self.sw_ai.set_style(ACCENT, "#FFFFFF")
            self.sw_local.set_style(CARD, INK, outline=LINE)
        else:
            self.sw_local.set_style(ACCENT, "#FFFFFF")
            self.sw_ai.set_style(CARD, INK, outline=LINE)
        self.sw_ai.set_enabled(bool(self.api_key))
        if not self.api_key:
            tip = "未配置 Key · 使用内置规则评分（离线、即时、结果可复现）"
        elif on:
            tip = "由 DeepSeek 逐维度点评 · 需联网，约 5–15 秒；调用失败会自动回退到内置规则"
        else:
            tip = "使用内置规则评分 · 已配置 Key，可切到 DeepSeek"
        self.eng_desc.configure(text=tip)

    def open_key_dialog(self):
        win = tk.Toplevel(self)
        win.title("DeepSeek API Key")
        win.configure(bg=BG)
        win.transient(self)
        win.resizable(False, False)
        f = tk.Frame(win, bg=BG)
        f.pack(fill="both", expand=True, padx=28, pady=24)
        tk.Label(f, text="DeepSeek API Key", bg=BG, fg=INK, font=F(13, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(f, text="填入后可用 DeepSeek 逐维度点评；留空则使用内置规则评分。\n"
                         "Key 以明文保存在 %s" % CONF_PATH,
                 bg=BG, fg=FAINT, font=F(9), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", pady=(5, 16))
        ent = self._key_widgets(f)
        brow = tk.Frame(f, bg=BG)
        brow.pack(fill="x", pady=(20, 0))
        RButton(brow, "保存", lambda: (self._commit_key(ent), win.destroy()),
                w=120, h=42, bg=BG, size=11).pack(side="right")
        RButton(brow, "取消", win.destroy, w=110, h=42, bg=BG, size=11,
                fill=CARD, fg=INK, outline=LINE).pack(side="right", padx=(0, 10))
        win.geometry("+%d+%d" % (self.winfo_rootx() + 80, self.winfo_rooty() + 110))
        ent.focus_set()

    # -------------------------------------------------- 选关页
    def open_select(self):
        self._commit_key(self.ent_key_start)
        self.render_select()
        self.show("select")
        self._autosize()

    def new_run(self):
        """清空成绩，重新开始一轮"""
        self.scores = {}
        self.open_select()

    def start_first(self):
        done = [i for i in range(len(TASKS)) if i not in self.scores]
        self.start_level(done[0] if done else 0)

    def start_level(self, i):
        self.idx = i
        self.load_level()
        self.show("level")
        self._autosize()

    def set_mode(self, m):
        self.mode = m
        self.render_select()

    def _build_select(self, root):
        pad = self._pad(root, 44, 30)

        head = tk.Frame(pad, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="选择关卡", bg=BG, fg=INK, font=F(20, "bold"),
                 anchor="w").pack(side="left")
        self.sel_hint = tk.Label(head, text="", bg=BG, fg=SUB, font=F(10), anchor="e")
        self.sel_hint.pack(side="right")

        mrow = tk.Frame(pad, bg=BG)
        mrow.pack(fill="x", pady=(16, 0))
        tk.Label(mrow, text="模式", bg=BG, fg=FAINT, font=F(10, "bold"),
                 anchor="w").pack(side="left", padx=(0, 14))
        self.sw_easy = RButton(mrow, "简单模式", lambda: self.set_mode("easy"),
                               w=124, h=38, size=11, bg=BG)
        self.sw_easy.pack(side="left")
        self.sw_hard = RButton(mrow, "困难模式", lambda: self.set_mode("hard"),
                               w=124, h=38, size=11, bg=BG)
        self.sw_hard.pack(side="left", padx=(8, 0))
        self.mode_desc = tk.Label(mrow, text="", bg=BG, fg=SUB, font=F(10),
                                  anchor="w", justify="left", wraplength=440)
        self.mode_desc.pack(side="left", padx=(18, 0))

        erow = tk.Frame(pad, bg=BG)
        erow.pack(fill="x", pady=(10, 0))
        tk.Label(erow, text="评分", bg=BG, fg=FAINT, font=F(10, "bold"),
                 anchor="w").pack(side="left", padx=(0, 14))
        self.sw_local = RButton(erow, "内置规则", lambda: self.set_engine("local"),
                                w=112, h=38, size=11, bg=BG)
        self.sw_local.pack(side="left")
        self.sw_ai = RButton(erow, "DeepSeek", lambda: self.set_engine("ai"),
                             w=112, h=38, size=11, bg=BG)
        self.sw_ai.pack(side="left", padx=(8, 0))
        self.btn_key = RButton(erow, "设置 Key", self.open_key_dialog, w=94, h=38,
                               size=10, bg=BG, fill=CARD, fg=SUB, outline=LINE)
        self.btn_key.pack(side="left", padx=(10, 0))
        self.eng_desc = tk.Label(erow, text="", bg=BG, fg=SUB, font=F(10),
                                 anchor="w", justify="left", wraplength=400)
        self.eng_desc.pack(side="left", padx=(16, 0))

        tk.Frame(pad, bg=BG).pack(fill="both", expand=True)   # 上方弹性留白，让卡片块居中
        self.sel_grid = tk.Frame(pad, bg=BG)
        self.sel_grid.pack(fill="x")
        self.sel_grid.columnconfigure(0, weight=1, uniform="l")
        self.sel_grid.columnconfigure(1, weight=1, uniform="l")

        self._sel_score = {}
        for i in range(len(TASKS)):
            self._make_level_card(i, i // 2, i % 2)

        tk.Frame(pad, bg=BG).pack(fill="both", expand=True)   # 下方弹性留白
        foot = tk.Frame(pad, bg=BG)
        foot.pack(fill="x", pady=(22, 0))
        RButton(foot, "重新开始", self.new_run, w=140, h=44,
                fill=CARD, fg=INK, outline=LINE).pack(side="left")
        RButton(foot, "查看成绩", self.goto_end, w=140, h=44,
                fill=CARD, fg=INK, outline=LINE).pack(side="left", padx=(12, 0))
        self.btn_go = RButton(foot, "从第 1 关开始", self.start_first, w=180, h=44)
        self.btn_go.pack(side="right")

    def _make_level_card(self, i, r, c):
        t = TASKS[i]
        padx = (0, 7) if c == 0 else (7, 0)
        box = tk.Frame(self.sel_grid, bg=CARD, highlightbackground=LINE,
                       highlightthickness=1, cursor="hand2")
        box.grid(row=r, column=c, sticky="nsew", padx=padx, pady=(0, 14))

        inner = tk.Frame(box, bg=CARD)
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x")
        no = tk.Label(top, text="%02d" % (i + 1), bg=CARD, fg=FAINT, font=F(11, "bold"))
        no.pack(side="left")
        stars = tk.Label(top, text="难度  " + "★" * t["diff"] + "☆" * (3 - t["diff"]),
                         bg=CARD, fg=SUB, font=F(9))
        stars.pack(side="right")
        name = tk.Label(inner, text=t["title"], bg=CARD, fg=INK, font=F(13, "bold"),
                        anchor="w")
        name.pack(fill="x", pady=(7, 5))
        score = tk.Label(inner, text="", bg=CARD, fg=SUB, font=F(10), anchor="w")
        score.pack(fill="x")
        self._sel_score[i] = score

        self._clickable(box, [box, inner, top, no, stars, name, score],
                        lambda k=i: self.start_level(k))

    def _clickable(self, frame, widgets, cmd):
        """整块卡片可点，并带 hover 反色"""
        def enter(_=None):
            for w in widgets:
                w.configure(bg=SOFT)

        def leave(_=None):
            for w in widgets:
                w.configure(bg=CARD)

        for w in widgets:
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda e: cmd())
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def render_select(self):
        easy = (self.mode == "easy")
        if easy:
            self.sw_easy.set_style(ACCENT, "#FFFFFF")
            self.sw_hard.set_style(CARD, INK, outline=LINE)
        else:
            self.sw_easy.set_style(CARD, INK, outline=LINE)
            self.sw_hard.set_style(ACCENT, "#FFFFFF")
        self.mode_desc.configure(
            text="简单模式：每个评分维度下面都标了「怎么写」，还能一键套用写作模板骨架。" if easy
            else "困难模式：只给任务和评分维度，不给任何提示——靠自己想清楚。")
        self.render_engine()

        for i in range(len(TASKS)):
            if i in self.scores:
                self._sel_score[i].configure(text="已挑战 · %d 分" % self.scores[i],
                                             fg=INK if self.scores[i] >= 70 else LOW)
            else:
                self._sel_score[i].configure(text="未挑战", fg=FAINT)

        n = len(self.scores)
        avg = int(round(sum(self.scores.values()) / float(n))) if n else 0
        self.sel_hint.configure(
            text="已完成 %d / %d 关 · 平均 %d 分" % (n, len(TASKS), avg) if n
            else "挑任意一关开始，不必从第一关打起")
        self.btn_go.set_text("从第 1 关开始" if not n else "继续未挑战的关卡")

    def goto_end(self):
        self.render_end()
        self.show("end")
        self._autosize()

    # -------------------------------------------------- 关卡页
    def _build_level(self, root):
        pad = self._pad(root, 44, 26)

        head = tk.Frame(pad, bg=BG)
        head.pack(fill="x")
        self.lv_kicker = tk.Label(head, text="", bg=BG, fg=FAINT, font=F(10, "bold"))
        self.lv_kicker.pack(side="left")
        self.lv_diff = tk.Label(head, text="", bg=BG, fg=SUB, font=F(11))
        self.lv_diff.pack(side="right")

        body = tk.Frame(pad, bg=BG)
        body.pack(fill="both", expand=True, pady=(14, 0))
        body.columnconfigure(0, weight=58, uniform="c")
        body.columnconfigure(1, weight=42, uniform="c")
        body.rowconfigure(0, weight=1)

        # 左：背景 + 任务
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.rowconfigure(1, weight=6)
        left.rowconfigure(3, weight=3)
        left.columnconfigure(0, weight=1)

        self._sec(left, 0, "任务背景")
        self.lv_bg = self._textbox(left, 1, 12, SUB)

        self._sec(left, 2, "你的任务")
        self.lv_task = self._textbox(left, 3, 13, INK, bg=SOFT, strong=True)

        # 右：自适应评分侧重
        right = card(body)
        right.grid(row=0, column=1, sticky="nsew")
        rh = tk.Frame(right, bg=CARD)
        rh.pack(fill="both", expand=True, padx=20, pady=18)
        tk.Label(rh, text="本关评分侧重", bg=CARD, fg=INK, font=F(12, "bold"),
                 anchor="w").pack(fill="x")
        self.lv_sub = tk.Label(rh, text="权重由任务场景自动生成，每关不同", bg=CARD, fg=FAINT,
                               font=F(9), anchor="w", justify="left", wraplength=330)
        self.lv_sub.pack(fill="x", pady=(3, 14))
        self.lv_rubric = tk.Frame(rh, bg=CARD)
        self.lv_rubric.pack(fill="x")
        self.lv_tip = tk.Label(rh, text="", bg=CARD, fg=SUB, font=F(10),
                               wraplength=330, justify="left", anchor="nw")
        self.lv_tip.pack(fill="x", side="bottom", pady=(14, 0))

        # 输入区
        inp_card = card(pad)
        inp_card.pack(fill="both", expand=True, pady=(18, 0))
        ih = tk.Frame(inp_card, bg=CARD)
        ih.pack(fill="both", expand=True, padx=20, pady=16)
        trow = tk.Frame(ih, bg=CARD)
        trow.pack(fill="x")
        tk.Label(trow, text="你的提示词", bg=CARD, fg=INK, font=F(12, "bold"),
                 anchor="w").pack(side="left")
        self.lv_count = tk.Label(trow, text="0 字", bg=CARD, fg=FAINT, font=F(10))
        self.lv_count.pack(side="right")

        self.lv_help = tk.Label(ih, text="", bg=CARD, fg=SUB, font=F(10),
                                anchor="w", justify="left", wraplength=840)

        self.input = tk.Text(ih, height=self._ih, width=1, wrap="word", font=F(11),
                             relief="flat",
                             bg="#FCFCFA", fg=INK, insertbackground=INK, undo=True,
                             padx=14, pady=12, highlightthickness=1,
                             highlightbackground=LINE, highlightcolor="#C9C6BF",
                             selectbackground="#E3E1DA", spacing1=3, spacing3=3)
        self.input.pack(fill="both", expand=True, pady=(10, 0))
        self._ph = "在这里写下你要交给 AI 的提示词……"
        self.input.insert("1.0", self._ph)
        self.input.configure(fg=FAINT)
        self.input.bind("<FocusIn>", self._in_focus)
        self.input.bind("<FocusOut>", self._out_focus)
        self.input.bind("<KeyRelease>", self._count)

        brow = tk.Frame(ih, bg=CARD)
        brow.pack(fill="x", pady=(14, 0))
        self.lv_hint = tk.Label(brow, text="", bg=CARD, fg=FAINT, font=F(10))
        self.lv_hint.pack(side="left")
        self.btn_submit = RButton(brow, "提交评分", self.submit, w=150, h=42,
                                  bg=CARD, size=11, fill=ACCENT, fg="#FFFFFF")
        self.btn_submit.pack(side="right")
        self.btn_tpl = RButton(brow, "套用写作模板", self.apply_template, w=152, h=42,
                               bg=CARD, size=11, fill=CARD, fg=INK, outline=LINE)

    def _sec(self, parent, row, text):
        tk.Label(parent, text=text, bg=BG, fg=FAINT, font=F(10, "bold"),
                 anchor="w").grid(row=row, column=0, sticky="w",
                                  pady=(0 if row == 0 else 14, 5))

    def _textbox(self, parent, row, size, fg, bg=CARD, strong=False, h=2):
        t = tk.Text(parent, height=h, width=1, wrap="word",
                    font=F(size, "bold" if strong else "normal"),
                    relief="flat", bg=bg, fg=fg, padx=16, pady=13, bd=0,
                    highlightthickness=1, highlightbackground=LINE,
                    selectbackground="#E3E1DA", spacing1=4, spacing3=4, cursor="arrow")
        t.grid(row=row, column=0, sticky="nsew")
        t.configure(state="disabled")
        t.bind("<Key>", lambda e: "break")
        return t

    def _in_focus(self, _=None):
        if self.input.get("1.0", "end-1c") == self._ph:
            self.input.delete("1.0", "end")
            self.input.configure(fg=INK)

    def _out_focus(self, _=None):
        if not self.input.get("1.0", "end-1c").strip():
            self.input.delete("1.0", "end")
            self.input.insert("1.0", self._ph)
            self.input.configure(fg=FAINT)

    def _count(self, _=None):
        n = len(self.get_prompt())
        self.lv_count.configure(text="%d 字" % n,
                                fg=INK if n >= 60 else FAINT)

    def get_prompt(self):
        s = self.input.get("1.0", "end-1c")
        return "" if s == self._ph else s

    def load_level(self):
        t = TASKS[self.idx]
        easy = (self.mode == "easy")
        self.lv_kicker.configure(
            text="关卡 %d / %d · %s" % (self.idx + 1, len(TASKS), t["title"]))
        self.lv_diff.configure(
            text=("简单模式 · " if easy else "困难模式 · ") +
                  "难度  " + "★" * t["diff"] + "☆" * (3 - t["diff"]))
        set_text(self.lv_bg, t["bg"])
        set_text(self.lv_task, t["task"])

        self.lv_sub.configure(
            text="权重由任务场景自动生成，每关不同" if not easy
            else "每个维度下面是「怎么写」的提示")

        hints = HINTS.get(self.idx, {}) if easy else {}
        for w in self.lv_rubric.winfo_children():
            w.destroy()
        for d in t["dims"]:
            box = tk.Frame(self.lv_rubric, bg=CARD)
            box.pack(fill="x", pady=(1, 7) if hints.get(d["name"]) else (1, 2))
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x")
            tk.Label(row, text=d["name"], bg=CARD, fg=INK, font=F(10),
                     anchor="w").pack(side="left")
            tk.Label(row, text="%d%%" % d["weight"], bg=CARD, fg=SUB, font=F(10),
                     anchor="e").pack(side="right")
            if hints.get(d["name"]):
                tk.Label(box, text=hints[d["name"]], bg=CARD, fg=SUB, font=F(9),
                         anchor="w", justify="left", wraplength=330).pack(fill="x",
                                                                          pady=(2, 0))
        self.lv_tip.configure(text="提示：" + t["tip"])
        self.lv_hint.configure(text="")

        self.btn_tpl.pack_forget()
        self.lv_help.pack_forget()
        if easy:
            self.btn_tpl.pack(side="right", padx=(0, 10))
            self.lv_help.pack(fill="x", pady=(7, 0), before=self.input)
            self.lv_help.configure(
                text="简单模式：照着右侧维度一条条对，拿不准就点「套用写作模板」，"
                     "再把【】里的空补掉。")

        self.input.delete("1.0", "end")
        self.input.insert("1.0", self._ph)
        self.input.configure(fg=FAINT)
        self._count()

    def apply_template(self):
        """把本关的写作骨架填进输入框，【】留给玩家自己补"""
        tpl = TEMPLATES.get(self.idx, "")
        if not tpl:
            return
        self.input.delete("1.0", "end")
        self.input.insert("1.0", tpl)
        self.input.configure(fg=INK)
        self.input.focus_set()
        self.input.mark_set("insert", "1.0")
        self.input.see("1.0")
        self._count()
        self.lv_hint.configure(text="模板已填入：把【】里的空换成你自己的内容即可。", fg=SUB)

    def submit(self):
        p = self.get_prompt().strip()
        if not p:
            self.lv_hint.configure(text="先写点什么，再提交。", fg=LOW)
            self.input.focus_set()
            return
        if self._ai_busy:
            return
        t = TASKS[self.idx]
        if self.ai_on():
            self._ask_ai(t, p)
        else:
            self._finish(t, p)

    # -------------------------------------------------- DeepSeek 审阅（异步）
    def _ask_ai(self, task, prompt):
        self._ai_busy = True
        self._ai_t0 = time.time()
        self._ai_dots = 0
        self.btn_submit.set_enabled(False)
        self.lv_hint.configure(text="DeepSeek 正在评审…", fg=SUB)
        threading.Thread(target=self._ai_worker, args=(task, prompt),
                         daemon=True).start()
        self.after(350, self._ai_pump)

    def _ai_worker(self, task, prompt):
        """工作线程只做网络请求，结果塞进队列，绝不碰界面"""
        try:
            res, err = ai_score(self.api_key, task, prompt)
        except Exception as e:
            res, err = None, _clip(e, 110)
        self._ai_q.put((task, prompt, res, err))

    def _ai_pump(self):
        """主线程轮询：转圈计时 + 收结果"""
        if not self._ai_busy:
            return
        try:
            task, prompt, res, err = self._ai_q.get_nowait()
        except queue.Empty:
            self._ai_dots = (self._ai_dots + 1) % 4
            self.lv_hint.configure(
                text="DeepSeek 正在逐维度评审%s（已 %.0f 秒）"
                     % ("·" * self._ai_dots, time.time() - self._ai_t0), fg=SUB)
            self.after(350, self._ai_pump)
            return

        self._ai_busy = False
        self.btn_submit.set_enabled(True)
        self.lv_hint.configure(text="", fg=SUB)
        if res is None:
            self._finish(task, prompt,
                         note="DeepSeek 调用失败：%s。本关已改用内置规则评分。" % err)
        else:
            self._finish(task, prompt, ai_res=res)

    def _finish(self, task, prompt, ai_res=None, note=None):
        """渲染评分页：有 AI 结果就用 AI 的，否则用内置规则"""
        if ai_res is not None:
            res = ai_res
            good, weak = ai_res["good"], ai_res["weak"]
        else:
            res = evaluate(task, prompt)
            res["engine"] = "local-fallback" if note else "local"
            if note:
                res["notes"] = [note] + res["notes"]
            good, weak = build_feedback(task, res)
        self.render_result(task, res, good, weak, prompt=prompt)
        self.show("result")
        self._autosize()

    # -------------------------------------------------- 评分页
    def _build_result(self, root):
        pad = self._pad(root, 44, 26)

        head = tk.Frame(pad, bg=BG)
        head.pack(fill="x")

        self.rs_engine = tk.Label(head, text="", bg=BG, fg=FAINT, font=F(9), anchor="e")
        self.rs_engine.pack(side="right", pady=(24, 0))

        self.rs_score = tk.Label(head, text="0", bg=BG, fg=INK, font=F(44, "bold"))
        self.rs_score.pack(side="left")
        tk.Label(head, text="分", bg=BG, fg=SUB, font=F(12)).pack(side="left",
                                                                  padx=(4, 16), pady=(18, 0))
        self.rs_badge = tk.Canvas(head, width=46, height=46, bg=BG, highlightthickness=0)
        self.rs_badge.pack(side="left", pady=(6, 0))
        self.rs_verdict = tk.Label(head, text="", bg=BG, fg=SUB, font=F(11),
                                   wraplength=560, justify="left", anchor="w")
        self.rs_verdict.pack(side="left", padx=18, pady=(14, 0), fill="x", expand=True)

        body = tk.Frame(pad, bg=BG)
        body.pack(fill="both", expand=True, pady=(16, 0))
        body.columnconfigure(0, weight=56, uniform="c")
        body.columnconfigure(1, weight=44, uniform="c")
        body.rowconfigure(0, weight=1)

        lc = card(body)
        lc.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        lh = tk.Frame(lc, bg=CARD)
        lh.pack(fill="both", expand=True, padx=20, pady=18)
        tk.Label(lh, text="维度得分", bg=CARD, fg=INK, font=F(12, "bold"),
                 anchor="w").pack(fill="x")
        self.rs_dims = tk.Frame(lh, bg=CARD)
        self.rs_dims.pack(fill="both", expand=True, pady=(12, 0))

        rc = card(body)
        rc.grid(row=0, column=1, sticky="nsew")
        rh = tk.Frame(rc, bg=CARD)
        rh.pack(fill="both", expand=True, padx=20, pady=18)
        tk.Label(rh, text="反馈", bg=CARD, fg=INK, font=F(12, "bold"),
                 anchor="w").pack(fill="x")
        self.rs_fb = tk.Frame(rh, bg=CARD)
        self.rs_fb.pack(fill="both", expand=True, pady=(12, 0))

        foot = tk.Frame(pad, bg=BG)
        foot.pack(fill="x", pady=(18, 0))
        self.btn_model = RButton(foot, "看参考提示词", self.show_model, w=160, h=44,
                                 fill=CARD, fg=INK, outline=LINE)
        self.btn_model.pack(side="left")
        self.btn_retry = RButton(foot, "重写本关", self.retry_level, w=140, h=44,
                                 fill=CARD, fg=INK, outline=LINE)
        self.btn_retry.pack(side="left", padx=(12, 0))
        self.btn_back = RButton(foot, "返回选关", self.open_select, w=132, h=44,
                                fill=CARD, fg=INK, outline=LINE)
        self.btn_back.pack(side="left", padx=(12, 0))
        self.btn_next = RButton(foot, "下一关", self.next_level, w=170, h=44)
        self.btn_next.pack(side="right")

    def render_result(self, task, res, good, weak, prompt=""):
        total = res.get("total", 0)
        self.rs_score.configure(text=str(total),
                                fg=GOOD if total >= 82 else
                                   MID if total >= 65 else LOW)
        # 等级徽章
        self.rs_badge.delete("all")
        rr(self.rs_badge, 1, 1, 45, 45, 10, fill=INK, outline=INK)
        self.rs_badge.create_text(23, 24, text=res.get("grade", "D"), fill="#FFFFFF",
                                  font=F(19, "bold"))
        self.rs_verdict.configure(
            text=res.get("verdict") or VERDICT.get(res.get("grade", "D"), ""))
        if res.get("ai"):
            self.rs_engine.configure(text="由 DeepSeek 评审", fg=SUB)
        elif res.get("engine") == "local-fallback":
            self.rs_engine.configure(text="由内置规则评审（DeepSeek 未成功）", fg=LOW)
        else:
            self.rs_engine.configure(text="由内置规则评审", fg=FAINT)

        # 维度
        for w in self.rs_dims.winfo_children():
            w.destroy()
        for d in res["dims"]:
            box = tk.Frame(self.rs_dims, bg=CARD)
            box.pack(fill="x", pady=(0, 11))
            r1 = tk.Frame(box, bg=CARD)
            r1.pack(fill="x")
            tk.Label(r1, text=d["name"], bg=CARD, fg=INK, font=F(10),
                     anchor="w").pack(side="left")
            tk.Label(r1, text="%d" % d["score"], bg=CARD,
                     fg=GOOD if d["score"] >= 82 else MID if d["score"] >= 65 else LOW,
                     font=F(10, "bold")).pack(side="right")
            cv = tk.Canvas(box, height=6, bg=CARD, highlightthickness=0)
            cv.pack(fill="x", pady=(5, 4))
            col = GOOD if d["score"] >= 82 else MID if d["score"] >= 65 else LOW
            cv.bind("<Configure>", lambda e, c=cv, s=d["score"], k=col:
                    self._draw_bar(c, s, k))
            if d.get("comment"):
                tk.Label(box, text=d["comment"], bg=CARD, fg=SUB, font=F(9),
                         anchor="w", wraplength=420, justify="left").pack(fill="x")
            elif d["type"] != "structural":
                info = ("命中：" + "、".join(d["hits"])) if d["hits"] else "未命中任何关键要求"
                tk.Label(box, text=info, bg=CARD,
                         fg=SUB if d["hits"] else LOW, font=F(9),
                         anchor="w", wraplength=420, justify="left").pack(fill="x")

        # 反馈
        for w in self.rs_fb.winfo_children():
            w.destroy()
        if res.get("notes"):
            for n in res["notes"]:
                self._fb_line(self.rs_fb, "!", n, LOW)
        if good:
            tk.Label(self.rs_fb, text="做对了", bg=CARD, fg=FAINT, font=F(9, "bold"),
                     anchor="w").pack(fill="x", pady=(4, 6))
            for g in good:
                self._fb_line(self.rs_fb, "✓", g, GOOD)
        if weak:
            tk.Label(self.rs_fb, text="可以更好", bg=CARD, fg=FAINT, font=F(9, "bold"),
                     anchor="w").pack(fill="x", pady=(14, 6))
            for w in weak:
                self._fb_line(self.rs_fb, "→", w, INK)
        if not weak and not res["notes"]:
            tk.Label(self.rs_fb, text="这一关没有明显短板，试试下一关。", bg=CARD, fg=SUB,
                     font=F(10), anchor="w", wraplength=360, justify="left").pack(fill="x")

        self._cur = (task, res, prompt)
        self.btn_model.set_text("看参考提示词")
        self.btn_next.set_text("查看结算" if self.idx == len(TASKS) - 1 else "下一关")
        self.scores[self.idx] = res["total"]
        self._autosize()

    def _draw_bar(self, cv, score, color):
        cv.delete("all")
        w = max(cv.winfo_width(), 10)
        rr(cv, 0, 1, w, 5, 2, fill="#EFEDE8", outline="#EFEDE8")
        fw = max(3, int(w * score / 100.0))
        rr(cv, 0, 1, fw, 5, 2, fill=color, outline=color)

    def _fb_line(self, parent, mark, text, color):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=mark, bg=CARD, fg=color, font=F(10, "bold"),
                 width=2, anchor="nw").pack(side="left")
        tk.Label(row, text=text, bg=CARD, fg=INK if color == INK else color,
                 font=F(10), wraplength=360, justify="left",
                 anchor="w").pack(side="left", fill="x", expand=True)

    def show_model(self):
        t, mine = self._cur[0], self._cur[2]
        win = tk.Toplevel(self)
        win.title("对照参考写法 · " + t["title"])
        win.configure(bg=BG)
        win.transient(self)
        w, h = min(900, self.winfo_width()), min(660, self.winfo_height())
        win.geometry("%dx%d+%d+%d" % (w, h, self.winfo_rootx() + 30,
                                      self.winfo_rooty() + 20))
        f = tk.Frame(win, bg=BG)
        f.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(f, text="对照参考写法", bg=BG, fg=INK,
                 font=F(14, "bold"), anchor="w").pack(fill="x")
        tk.Label(f, text="这不是标准答案，只是把本关的评分维度都照顾到的一种写法——"
                         "对比看看你的提示词漏了什么。",
                 bg=BG, fg=SUB, font=F(10), anchor="w", justify="left",
                 wraplength=w - 90).pack(fill="x", pady=(4, 14))

        box = tk.Frame(f, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        box.pack(fill="both", expand=True)
        txt = tk.Text(box, width=1, wrap="word", font=F(11), relief="flat", bg=CARD,
                      fg=INK, padx=20, pady=16, highlightthickness=0,
                      spacing1=3, spacing3=3, bd=0)
        sb = tk.Scrollbar(box, command=txt.yview, width=10, bd=0, relief="flat",
                          bg=CARD, troughcolor=CARD, activebackground=FAINT,
                          highlightthickness=0)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        txt.tag_configure("h", font=F(11, "bold"), foreground=INK,
                          spacing1=8, spacing3=8)
        txt.tag_configure("mine", font=F(11), foreground=SUB, spacing3=6)
        txt.tag_configure("ref", font=F(11), foreground=INK, spacing3=6)
        txt.insert("end", "你的提示词\n", "h")
        txt.insert("end", (mine or "（空）") + "\n\n", "mine")
        txt.insert("end", "参考写法\n", "h")
        txt.insert("end", t["model"], "ref")
        txt.configure(state="disabled")

        RButton(f, "关闭", win.destroy, w=130, h=42, bg=BG, size=11).pack(pady=(16, 0))

    def retry_level(self):
        """回到本关重写，成绩在下次提交时覆盖"""
        self.load_level()
        self.show("level")
        self._autosize()
        self.input.focus_set()

    def next_level(self):
        if self.idx >= len(TASKS) - 1:
            self.goto_end()
        else:
            self.start_level(self.idx + 1)

    # -------------------------------------------------- 结算页
    def _build_end(self, root):
        pad = self._pad(root, 44, 30)
        inner = tk.Frame(pad, bg=BG)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        self.en_title = tk.Label(inner, text="", bg=BG, fg=INK, font=F(11, "bold"))
        self.en_title.pack()
        self.en_score = tk.Label(inner, text="", bg=BG, fg=INK, font=F(46, "bold"))
        self.en_score.pack(pady=(6, 0))
        self.en_sub = tk.Label(inner, text="", bg=BG, fg=SUB, font=F(11))
        self.en_sub.pack(pady=(6, 24))

        self.en_list = tk.Frame(inner, bg=BG)
        self.en_list.pack()
        ef = tk.Frame(inner, bg=BG)
        ef.pack(pady=(28, 0))
        RButton(ef, "返回选关", self.open_select, w=150, h=48, size=12,
                bg=BG, fill=CARD, fg=INK, outline=LINE).pack(side="left")
        RButton(ef, "再玩一次", self.new_run, w=170, h=48, size=12).pack(side="left",
                                                                         padx=(12, 0))

    def render_end(self):
        done = [i for i in range(len(TASKS)) if i in self.scores]
        for w in self.en_list.winfo_children():
            w.destroy()

        if not done:
            self.en_title.configure(text="成绩单")
            self.en_score.configure(text="—", fg=FAINT)
            self.en_sub.configure(text="还没有成绩，先挑一关开始吧")
            self._autosize()
            return

        vals = [self.scores[i] for i in done]
        avg = int(round(sum(vals) / float(len(vals))))
        grade = ("S" if avg >= 92 else "A" if avg >= 82 else
                 "B" if avg >= 70 else "C" if avg >= 58 else "D")
        self.en_title.configure(text="通关" if len(done) == len(TASKS) else "成绩单")
        self.en_score.configure(text=str(avg),
                                fg=GOOD if avg >= 82 else MID if avg >= 65 else LOW)
        self.en_sub.configure(
            text="平均分 · 评级 %s · 已完成 %d / %d 关" % (grade, len(done), len(TASKS)))

        for i, t in enumerate(TASKS, 1):
            s = self.scores.get(i - 1)
            row = tk.Frame(self.en_list, bg=BG)
            row.pack(fill="x", pady=3)
            tk.Label(row, text="%02d  %s" % (i, t["title"]), bg=BG, fg=INK,
                     font=F(10), width=18, anchor="w").pack(side="left")
            cv = tk.Canvas(row, width=200, height=6, bg=BG, highlightthickness=0)
            cv.pack(side="left", padx=(10, 12))
            rr(cv, 0, 1, 200, 5, 2, fill="#EFEDE8", outline="#EFEDE8")
            if s is not None:
                col = GOOD if s >= 82 else MID if s >= 65 else LOW
                rr(cv, 0, 1, max(3, int(200 * s / 100)), 5, 2, fill=col, outline=col)
            else:
                col = FAINT
            tk.Label(row, text=(str(s) if s is not None else "未挑战"), bg=BG, fg=col,
                     font=F(10, "bold"), width=5, anchor="e").pack(side="left")
        self._autosize()


if __name__ == "__main__":
    App().mainloop()
