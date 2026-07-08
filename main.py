from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.agent.message import TextPart
from astrbot.core.message.components import At
from astrbot.core.platform.message_type import MessageType


PLUGIN_NAME = "astrbot_plugin_zhouli"

ASK_SYSTEM_PROMPT = """
你现在执行“问礼”任务：把用户给出的现代中文改写成人人能看懂、一本正经而略显荒唐的“周礼白话翻译腔”。
最高优先级是语义忠实：必须保留原话事实、对象、立场、判断、情绪、代词归属和谁对谁说话。
不要替用户纠错、劝解、辩驳、补充反方观点、缓和立场或改成更合理的意思；即使原话主观、偏激、荒唐、逻辑不成立或事实上可能是错的，也只做风格改写。
必须保留原句的言语行为：陈述句仍是陈述，疑问句仍是疑问，反问仍是反问，命令/请求仍是命令/请求，感叹仍是感叹；不要把疑问句改成结论，也不要把否定判断改成肯定或折中判断。
特别注意极性和量词：如“永远不会”“一定”“全都”“从不”“不是”等词义必须忠实保留，不得反转、弱化或偷换。
语言以现代白话为骨，像中学课本里的古文白话译文或古装剧里的清楚台词，让普通人一遍读懂；少用“吾、余、夫、矣、哉、乎、焉、兮”，不写成晦涩文言。
改写时要补出关系和名分：谁对谁、因何如此、谁该尽什么本分、乱了什么分寸、还有什么体面与信用。
要有论证感：可先讲一个能听懂的常识、饭食器物、行路宴席、古代旧事或自然现象，再转到眼前这句话；也可用“看似……其实……”“众人只看见……却没看见……”“如果……那么……”来铺陈。
可以使用“承认原话所说 -> 从原话立场内补理由 -> 用白话类比说明 -> 以定论或反问收束”的结构。这里的“转折”和“论据”只能帮助原句显得合礼、郑重或有梗，绝不能改变原句立场、判断、疑问方向或情绪。
如果原文是疑问句，论证只能解释“为什么会有此问/此问合乎何种名分”，最后仍要保持疑问或求问，不要代替用户回答。
自然使用“我听闻、当年、但是、所以、这样看来、难道”等连接词；适量点缀“君子、贤者、礼法、名分、职分、体面、分寸”等词，不连续堆砌。
如果原文是“我觉得坏人永远不会改过自新”，改写也必须表达“我认为坏人永远不会改过自新”，不能改成“我认为坏人并非永远不会改过自新”。
不得伪造“孔子说”“周公曰”“《周礼》有云”等真实出处，不输出写作说明，不加标题。
遇到辱骂、威胁、危险请求或违法内容时，不扩展操作细节、不美化伤害或违法行为；若只是改写一句话，仍应尽量忠实保留原句立场和句式，只把露骨表述处理得体面克制。
默认只输出改写结果。
""".strip()

PLAIN_SYSTEM_PROMPT = """
你现在执行“释礼”任务：把周礼体翻回清楚直接的人话。
不要继续写周礼体，不要新编古人故事，不要加标题和解释过程。
保留原文的对象、立场、判断、极性、句式、语气和社交关系。第一人称仍用“我/我们”。
陈述句仍是陈述，疑问句仍是疑问，反问仍是反问，命令/请求仍是命令/请求；不要替原文下判断或改成更合理的意思。
输出短、准、自然，像网友看懂后顺手解释。
""".strip()

MODE_HINT = """
本轮请保持“合乎周礼”的回复风格：
你不是单纯翻译用户文本，而是要回答用户当前问题，只是回答方式采用周礼白话翻译腔。
保持事实准确，不要编造出处，不要强行文言化。
优先让回答有礼法、名分、职分、体面的论证感；但如果用户问技术、事实或操作步骤，要先保证信息清楚可用，再适度周礼化。
""".strip()

LENGTH_HINTS = {
    "小礼": "输出约 70 到 130 字，像一条高赞短评；只保留一个短比喻或一层名分。",
    "成礼": "输出约 150 到 260 字，形成完整起承转合；尽量不要超过 300 字。",
    "大礼": "输出约 280 到 450 字，可以层层设喻，但每一层都要推进原句结论。",
}

DEFAULTS: dict[str, Any] = {
    "default_enabled": False,
    "require_mention_in_group": True,
    "ask_triggers": ["问礼：", "问礼:", "合乎周礼地说：", "把这句话变得合乎周礼："],
    "plain_triggers": ["释礼：", "释礼:", "翻回人话：", "解释这段周礼体："],
    "mode_on_triggers": ["进入周礼模式", "开启周礼模式", "以后合乎周礼地说话", "合乎周礼回答"],
    "mode_off_triggers": ["退出周礼模式", "关闭周礼模式", "退朝"],
    "default_length": "成礼",
    "max_input_chars": 800,
    "provider_id": "",
}


class ZhouLiState:
    def __init__(self, data_path: Path, default_enabled: bool = False):
        self.data_path = data_path
        self.default_enabled = default_enabled
        self.enabled_sessions: set[str] = set()
        self.disabled_sessions: set[str] = set()

    def load(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_path.exists():
            self.save()
            return
        try:
            payload = json.loads(self.data_path.read_text(encoding="utf-8"))
            self.enabled_sessions = set(payload.get("enabled_sessions", []))
            self.disabled_sessions = set(payload.get("disabled_sessions", []))
        except Exception as e:
            logger.warning(f"[ZhouLi] 状态文件读取失败，将使用空状态: {e}")
            self.enabled_sessions = set()
            self.disabled_sessions = set()

    def save(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "enabled_sessions": sorted(self.enabled_sessions),
            "disabled_sessions": sorted(self.disabled_sessions),
            "updated_at": int(time.time()),
        }
        self.data_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_enabled(self, session_key: str) -> bool:
        if session_key in self.enabled_sessions:
            return True
        if session_key in self.disabled_sessions:
            return False
        return self.default_enabled

    def enable(self, session_key: str) -> None:
        self.enabled_sessions.add(session_key)
        self.disabled_sessions.discard(session_key)
        self.save()

    def disable(self, session_key: str) -> None:
        self.enabled_sessions.discard(session_key)
        self.disabled_sessions.add(session_key)
        self.save()


@register(
    PLUGIN_NAME,
    "brov",
    "让 AstrBot 支持合乎周礼的问礼、释礼和会话回复风格。",
    "0.1.0",
)
class ZhouLiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = StarTools.get_data_dir()
        self.state = ZhouLiState(
            self.data_dir / "zhouli_state.json",
            default_enabled=self._cfg_bool("default_enabled"),
        )

    async def initialize(self) -> None:
        self.state.default_enabled = self._cfg_bool("default_enabled")
        self.state.load()
        logger.info("[ZhouLi] 合乎周礼插件已加载")

    async def terminate(self) -> None:
        self.state.save()
        logger.info("[ZhouLi] 合乎周礼插件已卸载")

    def _cfg(self, key: str) -> Any:
        return self.config.get(key, DEFAULTS[key])

    def _cfg_bool(self, key: str) -> bool:
        return bool(self._cfg(key))

    def _cfg_list(self, key: str) -> list[str]:
        value = self._cfg(key)
        if not isinstance(value, list):
            return list(DEFAULTS[key])
        return [str(item) for item in value if str(item).strip()]

    def _session_key(self, event: AstrMessageEvent) -> str:
        return event.unified_msg_origin

    @staticmethod
    def _strip_command_text(message: str, command_names: set[str]) -> str:
        message = re.sub(r"\s+", " ", message.strip())
        for command_name in sorted(command_names, key=len, reverse=True):
            for candidate in (command_name, f"/{command_name}"):
                if message == candidate:
                    return ""
                if message.startswith(f"{candidate} "):
                    return message[len(candidate) :].strip()
        return ""

    def _is_group_chat(self, event: AstrMessageEvent) -> bool:
        try:
            return event.get_message_type() != MessageType.FRIEND_MESSAGE
        except Exception:
            return bool(event.get_group_id())

    def _is_mentioned(self, event: AstrMessageEvent) -> bool:
        self_id = str(event.get_self_id() or "").strip()
        if not self_id:
            return False
        for comp in event.get_messages():
            if isinstance(comp, At) and str(comp.qq).strip() == self_id:
                return True
        return False

    def _is_addressed(self, event: AstrMessageEvent) -> bool:
        if not self._is_group_chat(event):
            return True
        if not self._cfg_bool("require_mention_in_group"):
            return True
        return bool(event.is_at_or_wake_command or event.is_wake_up() or self._is_mentioned(event))

    def _limit_text(self, text: str) -> tuple[bool, str]:
        max_chars = max(1, int(self._cfg("max_input_chars")))
        text = text.strip()
        if not text:
            return False, "请补上要处理的文字。"
        if len(text) > max_chars:
            return False, f"文字太长了，请控制在 {max_chars} 字以内。"
        return True, text

    def _style_suffix(self) -> str:
        length = str(self._cfg("default_length") or DEFAULTS["default_length"])
        return "\n".join(
            [
                "辞气自择：不要套用固定辞气或预设档位。请根据用户原文的意图、人物关系、情绪强度、场合正式程度和潜在风险，自行推导最合适的周礼式语气。需要劝慰就先体谅再讲分寸，需要争辩就建立貌似严谨的论证，需要圆场就另立名分，需要谴责就把小事提升到秩序与礼法；但所有辞气都必须忠实服务当前文本，不能替原文改变立场、极性、疑问方向或结论。",
                "论证要求：默认不要只做逐字换词；应补关系、释名分、作白话类比，并用一两层能听懂的理由把原句说得合乎周礼。论据可以荒唐但要自洽，可以夸张但不得新增会改变原意的事实。",
                f"默认篇幅：{length}。{LENGTH_HINTS.get(length, '')}".strip(),
            ],
        )

    @staticmethod
    def _clean_output(text: str) -> str:
        result = (text or "").strip()
        result = re.sub(r"^```(?:text|markdown)?\s*", "", result, flags=re.I).strip()
        result = re.sub(r"\s*```$", "", result).strip()
        prefixes = [
            "好的，",
            "好的。",
            "以下是",
            "当然可以，",
            "问礼结果：",
            "释礼结果：",
            "改写结果：",
            "人话解释：",
        ]
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if result.startswith(prefix):
                    result = result[len(prefix) :].lstrip(" ：:\n")
                    changed = True
        return result.strip()

    async def _get_provider_id(self, event: AstrMessageEvent) -> str:
        configured = str(self._cfg("provider_id") or "").strip()
        if configured:
            return configured
        return await self.context.get_current_chat_provider_id(event.unified_msg_origin)

    async def _generate(self, event: AstrMessageEvent, system_prompt: str, user_text: str) -> str:
        provider_id = await self._get_provider_id(event)
        prompt = f"{user_text}\n\n请只输出结果，不要加标题和解释。"
        response = await self.context.llm_generate(
            chat_provider_id=provider_id,
            system_prompt=f"{system_prompt}\n{self._style_suffix()}",
            prompt=prompt,
        )
        return self._clean_output(response.completion_text)

    async def _reply_conversion(
        self,
        event: AstrMessageEvent,
        system_prompt: str,
        text: str,
    ):
        ok, payload = self._limit_text(text)
        if not ok:
            yield event.plain_result(payload)
            event.stop_event()
            return
        try:
            result = await self._generate(event, system_prompt, payload)
        except Exception as e:
            logger.error(f"[ZhouLi] 调用 LLM 失败: {e}", exc_info=True)
            yield event.plain_result(f"问礼失败：当前 LLM provider 不可用或返回异常。{e}")
            event.stop_event()
            return
        yield event.plain_result(result or "问礼无言，模型未返回内容。")
        event.stop_event()

    @filter.command("zhouli", alias={"周礼"})
    async def zhouli(self, event: AstrMessageEvent, action: str = "status", text: str = ""):
        """管理周礼模式：/zhouli on、/zhouli off、/zhouli status、/zhouli ask 文本、/zhouli plain 文本。"""
        normalized = (action or "status").strip().lower()
        if normalized in {"on", "开启", "enable", "进入"}:
            self.state.enable(self._session_key(event))
            yield event.plain_result("礼门已开。此后本席言语，自当略合周礼。")
            event.stop_event()
            return
        if normalized in {"off", "关闭", "disable", "退出", "退朝"}:
            self.state.disable(self._session_key(event))
            yield event.plain_result("礼成而退。此后恢复常言。")
            event.stop_event()
            return
        if normalized in {"status", "状态", "check"}:
            status = "已开启" if self.state.is_enabled(self._session_key(event)) else "未开启"
            yield event.plain_result(f"当前会话周礼模式：{status}")
            event.stop_event()
            return
        if normalized in {"help", "帮助"}:
            yield event.plain_result(self._help_text())
            event.stop_event()
            return
        if normalized in {"ask", "问礼", "wenli"}:
            raw_text = self._strip_command_text(event.get_message_str(), {"zhouli", "周礼"})
            payload = raw_text.split(" ", 1)[1] if " " in raw_text else str(text)
            async for result in self._reply_conversion(event, ASK_SYSTEM_PROMPT, payload):
                yield result
            return
        if normalized in {"plain", "释礼", "shili"}:
            raw_text = self._strip_command_text(event.get_message_str(), {"zhouli", "周礼"})
            payload = raw_text.split(" ", 1)[1] if " " in raw_text else str(text)
            async for result in self._reply_conversion(event, PLAIN_SYSTEM_PROMPT, payload):
                yield result
            return
        yield event.plain_result("未知周礼命令。发送 /zhouli help 查看用法。")
        event.stop_event()

    @filter.command("问礼", alias={"wenli"})
    async def ask_zhouli(self, event: AstrMessageEvent, text: str = ""):
        """把现代中文改写成周礼体。"""
        payload = self._strip_command_text(event.get_message_str(), {"问礼", "wenli"}) or str(text)
        async for result in self._reply_conversion(event, ASK_SYSTEM_PROMPT, payload):
            yield result

    @filter.command("释礼", alias={"shili"})
    async def plain_zhouli(self, event: AstrMessageEvent, text: str = ""):
        """把周礼体翻回人话。"""
        payload = self._strip_command_text(event.get_message_str(), {"释礼", "shili"}) or str(text)
        async for result in self._reply_conversion(event, PLAIN_SYSTEM_PROMPT, payload):
            yield result

    @filter.event_message_type(EventMessageType.ALL)
    async def listen_natural_triggers(self, event: AstrMessageEvent):
        """监听明确自然语言触发词。"""
        text = event.get_message_str().strip()
        if not text or text.startswith("/"):
            return
        if not self._is_addressed(event):
            return

        if text in self._cfg_list("mode_on_triggers"):
            self.state.enable(self._session_key(event))
            yield event.plain_result("礼门已开。此后本席言语，自当略合周礼。")
            event.stop_event()
            return
        if text in self._cfg_list("mode_off_triggers"):
            self.state.disable(self._session_key(event))
            yield event.plain_result("礼成而退。此后恢复常言。")
            event.stop_event()
            return

        for trigger in self._cfg_list("ask_triggers"):
            if text.startswith(trigger):
                raw = text[len(trigger) :].strip()
                async for result in self._reply_conversion(event, ASK_SYSTEM_PROMPT, raw):
                    yield result
                return
        for trigger in self._cfg_list("plain_triggers"):
            if text.startswith(trigger):
                raw = text[len(trigger) :].strip()
                async for result in self._reply_conversion(event, PLAIN_SYSTEM_PROMPT, raw):
                    yield result
                return

    @filter.on_llm_request()
    async def inject_zhouli_style(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """给已开启周礼模式的会话追加临时风格提示。"""
        if not self.state.is_enabled(self._session_key(event)):
            return
        hint = f"{MODE_HINT}\n{self._style_suffix()}"
        try:
            req.extra_user_content_parts.append(TextPart(text=f"<zhouli_style>\n{hint}\n</zhouli_style>"))
        except Exception:
            req.system_prompt += f"\n\n{hint}"
        logger.debug("[ZhouLi] 已为本轮 LLM 请求追加周礼风格提示")

    @staticmethod
    def _help_text() -> str:
        return "\n".join(
            [
                "合乎周礼插件用法：",
                "/zhouli on - 开启当前会话周礼模式",
                "/zhouli off - 关闭当前会话周礼模式",
                "/zhouli status - 查看当前会话状态",
                "/zhouli ask <文本> - 把文本改写成周礼体",
                "/zhouli plain <文本> - 把周礼体翻回人话",
                "/问礼 <文本> - 单次问礼转换",
                "/释礼 <文本> - 单次释礼转换",
            ],
        )
