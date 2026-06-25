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
        role_cn = roles_db[self.initial_role]["name_cn"]
        ability = roles_db[self.initial_role]["ability"]
        strategies = "\n".join([f"- {s}" for s in roles_db[self.initial_role]["strategies"]])

        self.system_instruction = f"""你是《一夜终极狼人》游戏中的玩家：{self.player_name}。
        你的初始底牌是：【{role_cn}】。

        游戏基本规则：
        1. 本局共有6名玩家 (玩家1-6) 和3张中央牌 (中央0, 1, 2)。
        2. 狼人阵营 (2个狼人、1个爪牙)；村民阵营 (1个预言家、1个强盗、1个捣蛋鬼、2个守夜人、1个酒鬼)。
        3. 胜利条件：
           - 如果村民投票淘汰了至少一只【狼人】，则村民阵营获胜。
           - 如果没有淘汰【狼人】（比如淘汰了【爪牙】或【村民】），则狼人阵营获胜。
           - 特殊情况：如果场上没有狼人被派发给玩家（即狼人都在中央牌），必须所有人每人都只得1票（即没有玩家被淘汰，如每个人都投自己），村民阵营才能获胜。如果有任何玩家在此情况下被投死，则狼人阵营获胜。
        4. 在夜间，某些角色的牌可能会被交换（如强盗、捣蛋鬼、酒鬼）。你目前知道自己的初始底牌，但你的牌有可能在夜间被换走。
        5. 你需要结合白天大家的发言，推理出自己当前的真实身份，并极力帮助自己的阵营（即你初始底牌所代表的阵营，除非你确信你被换了牌）获胜。
        6. 狼人要互相打配合、说谎或假跳身份。爪牙需要保护狼人、替狼人挡刀或吸引火力（爪牙死了但狼人没死，狼人赢）。村民需要通过逻辑排除法推理出真相。

        你扮演的角色【{role_cn}】技能描述：
        {ability}

        你角色的最优策略建议：
        {strategies}

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

        config_dict = {
            "system_instruction": self.system_instruction,
            "temperature": self.temp,
            "response_mime_type": "application/json",
            "response_schema": DayStatement,
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
        
        config_dict = {
            "system_instruction": self.system_instruction,
            "temperature": 0.2, # Lower temp for logical night actions
            "response_mime_type": "application/json",
            "response_schema": schema,
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

        config_dict = {
            "system_instruction": self.system_instruction,
            "temperature": self.temp,
            "response_mime_type": "application/json",
            "response_schema": VoteAction,
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
