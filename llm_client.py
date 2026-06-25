# llm_client.py
import json
import random
import time
from google import genai
from google.genai import types
from google.genai import errors
from pydantic import BaseModel, Field
import config

# Initialize the Gemini Client
# Assumes GEMINI_API_KEY environment variable is set
client = genai.Client()

def generate_content_with_retry(contents, config_dict) -> genai.types.GenerateContentResponse:
    """Helper function to execute model generation with exponential backoff retries on transient errors."""
    max_retries = 5
    base_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(**config_dict)
            )
            return response
        except errors.APIError as e:
            # Retry on 503 (high demand), 429 (rate limit), and 500 (internal error)
            if e.code in [503, 429, 500] and attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 1.0)
                time.sleep(sleep_time)
                continue
            raise e
        except Exception as e:
            # Handle other transient connection drops/network issues
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 1.0)
                time.sleep(sleep_time)
                continue
            raise e

# Day phase structured output schema
class DayStatement(BaseModel):
    thought: str = Field(
        description="你的内心真实想法、逻辑分析、心理战术以及下一步的计划（不对外公开）"
    )
    statement: str = Field(
        description="你说给其他所有玩家听的公开言论，可以撒谎、试探、指控或顺从（对外公开）"
    )

# Night action schemas
class SeerAction(BaseModel):
    target_type: str = Field(
        description="选择查看对象，只能是 'player' 或 'center' 中的一个"
    )
    player_id: int = Field(
        description="如果target_type是 'player'，选择查看的玩家ID (1-6)，否则填 0",
        default=0
    )
    center_indices: list[int] = Field(
        description="如果target_type是 'center'，选择查看的中央牌索引(必须选择2张，如 [0, 1] 或 [1, 2] 等)，否则填空列表 []",
        default=[]
    )

class RobberAction(BaseModel):
    target_player_id: int = Field(
        description="选择你要交换身份并查看新身份的玩家ID (1-6)，不能选你自己"
    )

class TroublemakerAction(BaseModel):
    player_id_1: int = Field(
        description="你要交换身份牌的第一个玩家ID (1-6)，不能是你自己"
    )
    player_id_2: int = Field(
        description="你要交换身份牌的第二个玩家ID (1-6)，不能是你自己，且不能与第一个相同"
    )

class DrunkAction(BaseModel):
    center_index: int = Field(
        description="选择你要在中央三张牌中进行交换的牌索引 (0, 1, 或 2)，你不允许查看新牌"
    )

# Voting schema
class VoteAction(BaseModel):
    thought: str = Field(
        description="你的内心投票动机、最后的推理逻辑"
    )
    target_player_id: int = Field(
        description="你投票淘汰的玩家ID (1-6)。如果你确信没有狼人，可以投你自己以实现平票，让村民阵营获胜"
    )

class LLMPlayer:
    def __init__(self, player_id: int, player_name: str, initial_role: str, is_human: bool = False):
        self.player_id = player_id
        self.player_name = player_name
        self.initial_role = initial_role
        self.current_role = initial_role  # Starts the same, may change during the night
        self.is_human = is_human
        
        # History maintains alternating user/model turns.
        self.history: list[types.Content] = []
        self.system_instruction = ""
        self.temp = config.DEFAULT_TEMP

    def initialize_system_prompt(self, roles_db: dict):
        """Builds the system instruction for this player based on their initial role and rules."""
        import os
        role_cn = roles_db[self.initial_role]["name_cn"]
        ability = roles_db[self.initial_role]["ability"]
        strategies = "\n".join([f"- {s}" for s in roles_db[self.initial_role]["strategies"]])

        # Load past reflection if exists
        reflection_str = ""
        reflection_path = f"reflections/{self.initial_role}.md"
        if os.path.exists(reflection_path):
            try:
                with open(reflection_path, "r", encoding="utf-8") as f:
                    reflection_str = f.read().strip()
            except Exception:
                pass
                
        reflection_instruction = ""
        if reflection_str:
            reflection_instruction = f"\n\n以下是你在过往游戏局中总结并沉淀的【{role_cn}】经验与心得体会，请务必学习并融入到你这局的游戏策略中：\n{reflection_str}"

        from collections import Counter
        deck_counts = Counter(config.DECK_ROLES)
        deck_desc_list = []
        for role, count in deck_counts.items():
            role_cn = roles_db[role]["name_cn"]
            deck_desc_list.append(f"{role_cn} ({role}): {count}个")
        deck_description = "，".join(deck_desc_list)

        rules_list = []
        for role in sorted(list(set(config.DECK_ROLES))):
            role_cn = roles_db[role]["name_cn"]
            role_ability = roles_db[role]["ability"]
            rules_list.append(f"- **{role_cn} ({role})**：{role_ability}")
        all_rules_description = "\n        ".join(rules_list)

        self.system_instruction = f"""你是《一夜终极狼人》游戏中的玩家：{self.player_name}。
        你的初始底牌是：【{role_cn}】。

        游戏基本规则：
        1. 本局共有6名玩家 (玩家1-6) 和3张中央牌 (中央0, 1, 2)。
        2. 本局配置的牌堆角色分布为：{deck_description}。
        3. 胜利条件：
           - 如果村民投票淘汰了至少一只【狼人】，则村民阵营获胜。
           - 如果没有淘汰【狼人】（比如淘汰了【爪牙】或【村民】），则狼人阵营获胜.
           - 特殊情况：如果场上没有狼人被派发给玩家（即狼人都在中央牌），必须所有人每人都只得1票（即没有玩家被淘汰，如每个人都投自己），村民阵营才能获胜。如果有任何玩家在此情况下被投死，则狼人阵营获胜。
        4. 在夜间，某些角色的牌可能会被交换（如强盗、捣蛋鬼、酒鬼）。你目前知道自己的初始底牌，但你的牌有可能在夜间被换走。
        5. 你需要结合白天大家的发言，推理出自己当前的真实身份，并极力帮助自己的阵营（即你初始底牌所代表的阵营，除非你确信你被换了牌）获胜。
        6. 狼人要互相打配合、说谎或假跳身份。爪牙需要保护狼人、替狼人挡刀或吸引火力（爪牙死了但狼人没死，狼人赢）。村民需要通过逻辑排除法推理出真相。

        本局涉及的所有角色技能规则描述（供你发言和伪装时推理参考）：
        {all_rules_description}

        你扮演的角色【{role_cn}】技能描述：
        {ability}

        你角色的最优策略建议：
        {strategies}
        {reflection_instruction}

        请严格遵守你的角色设定，隐藏自己的真实信息（如果是坏人），或者策略性地透露信息（如果是好人），来误导对手、帮助队友。
        """

    def add_message(self, role: str, text: str):
        """Manually append a message to the player's conversation context history."""
        self.history.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=text)]
            )
        )

    def generate_day_statement(self, current_round_context: str) -> tuple[str, str]:
        """Queries the model for their day phase thought and statement (JSON)."""
        if self.is_human:
            return "Human thought", ""

        # Create user prompt for the turn
        user_prompt = f"""现在是白天讨论发言环节。
        当前轮次与之前的对话历史如下：
        {current_round_context}

        请输出你的内心想法（thought）以及你的公开言论（statement）。
        """
        
        contents = list(self.history)
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_prompt)]
            )
        )

        thinking_level = config.DEFAULT_THINKING_LEVEL
        if thinking_level == "OFF":
            thinking_config = types.ThinkingConfig(thinking_budget=0)
        else:
            thinking_config = types.ThinkingConfig(thinking_level=thinking_level)

        config_dict = {
            "system_instruction": self.system_instruction,
            "temperature": self.temp,
            "response_mime_type": "application/json",
            "response_schema": DayStatement,
            "thinking_config": thinking_config,
        }

        response = generate_content_with_retry(contents, config_dict)

        try:
            res_json = json.loads(response.text)
            thought = res_json.get("thought", "")
            statement = res_json.get("statement", "")
            return thought, statement
        except Exception as e:
            return f"Parsing error: {e}", f"我是 {self.player_name}，我认为我们要仔细分析。"

    def query_night_action(self, schema) -> dict:
        """Queries the model for their night action based on the role schema."""
        if self.is_human:
            return {}

        role_cn = self.initial_role
        user_prompt = f"""夜深了，现在是【{role_cn}】行动的时刻。
        请根据你的角色技能，输出你的夜间行动选择。
        """
        
        thinking_level = config.DEFAULT_THINKING_LEVEL
        if thinking_level == "OFF":
            thinking_config = types.ThinkingConfig(thinking_budget=0)
        else:
            thinking_config = types.ThinkingConfig(thinking_level=thinking_level)

        config_dict = {
            "system_instruction": self.system_instruction,
            "temperature": 0.2, # Lower temp for logical night actions
            "response_mime_type": "application/json",
            "response_schema": schema,
            "thinking_config": thinking_config,
        }
        
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)])]
        
        response = generate_content_with_retry(contents, config_dict)
        try:
            return json.loads(response.text)
        except Exception:
            return {}

    def query_vote(self, discussion_log: str) -> tuple[str, int]:
        """Queries the model for their final vote and thought process."""
        if self.is_human:
            return "Human vote thought", 0

        user_prompt = f"""白天的讨论已经结束，现在进入投票淘汰环节。
        以下是完整的讨论记录：
        {discussion_log}

        请进行你的秘密投票。输出你的内心投票动机（thought）以及你投给的玩家ID (1-6)。
        """
        contents = list(self.history)
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_prompt)]
            )
        )

        thinking_level = config.DEFAULT_THINKING_LEVEL
        if thinking_level == "OFF":
            thinking_config = types.ThinkingConfig(thinking_budget=0)
        else:
            thinking_config = types.ThinkingConfig(thinking_level=thinking_level)

        config_dict = {
            "system_instruction": self.system_instruction,
            "temperature": self.temp,
            "response_mime_type": "application/json",
            "response_schema": VoteAction,
            "thinking_config": thinking_config,
        }

        response = generate_content_with_retry(contents, config_dict)
        try:
            res_json = json.loads(response.text)
            thought = res_json.get("thought", "")
            vote_target = res_json.get("target_player_id", self.player_id)
            vote_target = max(1, min(6, vote_target))
            return thought, vote_target
        except Exception:
            return "无法解析投票", self.player_id

    def generate_reflection(self, is_victory: bool, winner: str, outcome_reason: str, night_logs: str, discussion_log: str, private_thoughts: str) -> str:
        """Queries the model to review the game and update its role reflection markdown."""
        import os
        
        old_reflection = ""
        os.makedirs("reflections", exist_ok=True)
        reflection_path = f"reflections/{self.initial_role}.md"
        if os.path.exists(reflection_path):
            try:
                with open(reflection_path, "r", encoding="utf-8") as f:
                    old_reflection = f.read()
            except Exception:
                pass

        victory_status = "【胜利】" if is_victory else "【失败】"
        
        user_prompt = f"""游戏结束了。你本局的初始角色是：【{self.initial_role}】（最终角色是：【{self.current_role}】）。
        你的初始阵营在本局中最终是：{victory_status}。
        胜利阵营是：{winner} 阵营。胜负原因：{outcome_reason}
        
        夜间详细行动日志：
        {night_logs}
        
        白天发言的完整公共记录：
        {discussion_log}
        
        你在讨论阶段每轮的内心真实想法：
        {private_thoughts}
        
        请作为【{self.initial_role}】这个角色的资深玩家，对这局游戏进行复盘，总结经验与教训。
        如果是你扮演的 AI 玩家（或人类玩家）做错了，请指出哪里可以改进；如果做对了，请总结成功的打法。
        
        请输出一份更新后的《{self.initial_role}角色心得体会》Markdown 文档。
        
        格式与规则要求：
        1. 必须使用 Markdown 格式。
        2. 如果下方提供了旧的心得体会，请把旧的有用经验保留，并与这局的新教训进行融合整理。不要直接丢弃旧的心得体会。
        3. 请将输出严格限制在 4096 字节（约 1000 个汉字）以内，精简干练，不要包含任何多余的客套话或外围包裹文本。
        
        以下是历史的心得体会（如果有的话，供参考融合）：
        ---
        {old_reflection}
        ---
        """
        
        config_dict = {
            "temperature": 0.6,
            "max_output_tokens": 1200
        }
        
        response = generate_content_with_retry(
            [types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)])],
            config_dict
        )
        return response.text
