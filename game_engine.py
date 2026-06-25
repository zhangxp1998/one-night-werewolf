# game_engine.py
import json
import random
import config
from llm_client import LLMPlayer, SeerAction, RobberAction, TroublemakerAction, DrunkAction

class OneNightEngine:
    def __init__(self):
        # Load roles metadata
        with open("roles_config.json", "r", encoding="utf-8") as f:
            self.roles_db = json.load(f)
            
        self.player_count = config.DEFAULT_PLAYER_COUNT
        self.deck = list(config.DECK_ROLES)
        
        # State variables
        self.players: dict[int, LLMPlayer] = {}
        self.original_player_roles: dict[int, str] = {}
        self.current_player_roles: dict[int, str] = {}
        self.original_center_cards: list[str] = []
        self.current_center_cards: list[str] = []
        
        # Game Logs
        self.night_logs: list[str] = []         # Detailed spoiler log for game-over screen
        self.public_night_logs: list[str] = []  # Generic progress log for gameplay screen
        self.public_discussion_log: list[str] = []
        self.private_thoughts: dict[int, list[str]] = {i: [] for i in range(1, self.player_count + 1)}
        
    def setup_game(self, human_player_id: int = None):
        """Shuffles cards and initializes players."""
        shuffled_deck = list(self.deck)
        random.shuffle(shuffled_deck)
        
        # Deal to players
        for i in range(1, self.player_count + 1):
            role = shuffled_deck[i - 1]
            self.original_player_roles[i] = role
            self.current_player_roles[i] = role
            
            is_human = (i == human_player_id)
            player_name = f"玩家 {i}" + (" (你)" if is_human else "")
            self.players[i] = LLMPlayer(
                player_id=i,
                player_name=player_name,
                initial_role=role,
                is_human=is_human
            )
            self.players[i].initialize_system_prompt(self.roles_db)
            
        # Deal to center
        self.original_center_cards = shuffled_deck[self.player_count:]
        self.current_center_cards = list(self.original_center_cards)
        
        self.night_logs = ["游戏准备就绪。"]
        self.public_night_logs = ["🌙 夜幕降临，所有人请闭眼..."]
        self.public_discussion_log = []
        self.private_thoughts = {i: [] for i in range(1, self.player_count + 1)}

    def get_player_role_cn(self, player_id: int) -> str:
        role = self.current_player_roles[player_id]
        return self.roles_db[role]["name_cn"]

    # ----------------- DISCRETE NIGHT PHASE STEPS -----------------
    
    def night_werewolf(self, center_choice: int = None) -> bool:
        """Runs Werewolf actions. Returns True if human lone wolf choice is needed."""
        werewolf_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Werewolf"]
        self.public_night_logs.append("🐺 狼人，请睁眼...")
        
        if len(werewolf_players) == 2:
            p1, p2 = werewolf_players
            self.players[p1].add_message("user", f"夜间你与另一名狼人 {self.players[p2].player_name} 确认了彼此的身份。")
            self.players[p2].add_message("user", f"夜间你与另一名狼人 {self.players[p1].player_name} 确认了彼此的身份。")
            self.night_logs.append(f"狼人 【玩家 {p1}】 和 【玩家 {p2}】 互相确认了身份。")
            self.public_night_logs.append("狼人们睁眼并确认了彼此的同伴身份。")
            return False
        elif len(werewolf_players) == 1:
            lone_wolf_id = werewolf_players[0]
            lone_wolf = self.players[lone_wolf_id]
            
            if lone_wolf.is_human:
                if center_choice is None:
                    self.night_logs.append(f"只有一名独狼：【玩家 {lone_wolf_id}】。等待其选择查看中央底牌。")
                    self.public_night_logs.append("独狼玩家正在选择查看中央底牌...")
                    return True
                choice = center_choice
            else:
                if config.LLM_DRIVEN_NIGHT_ACTIONS:
                    action = lone_wolf.query_night_action(DrunkAction)  # reuse index choice
                    choice = action.get("center_index", 0)
                else:
                    choice = random.randint(0, 2)
                    
            choice = max(0, min(2, choice))
            revealed_role = self.current_center_cards[choice]
            revealed_role_cn = self.roles_db[revealed_role]["name_cn"]
            lone_wolf.add_message("user", f"夜间睁眼，你没有看到其他狼人。你查看了中央牌 {choice}，它是：【{revealed_role_cn}】。")
            
            self.night_logs.append(f"独狼 【玩家 {lone_wolf_id}】 查看了中央牌 {choice}，角色是：{revealed_role_cn}。")
            self.public_night_logs.append("独狼睁眼，并选择查看了一张中央牌。")
            return False
        else:
            self.night_logs.append("场上没有狼人睁眼。")
            self.public_night_logs.append("场上没有狼人睁眼。")
            return False

    def night_minion(self) -> bool:
        """Runs Minion action. Returns False."""
        minion_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Minion"]
        werewolf_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Werewolf"]
        self.public_night_logs.append("🟡 爪牙，请睁眼...")
        if minion_players:
            m_id = minion_players[0]
            minion = self.players[m_id]
            if werewolf_players:
                wolves_str = ", ".join([self.players[w].player_name for w in werewolf_players])
                minion.add_message("user", f"夜间睁眼，主持人向你指示：场上的狼人是 {wolves_str}。")
                self.night_logs.append(f"爪牙 【玩家 {m_id}】 确认了狼人队友：{wolves_str}。")
            else:
                minion.add_message("user", "夜间睁眼，主持人向你指示：场上没有狼人被分发（均在中央）。")
                self.night_logs.append(f"爪牙 【玩家 {m_id}】 睁眼，但得知场上没有狼人。")
            self.public_night_logs.append("爪牙睁眼，主持人已向其示意了场上的狼人队友。")
        else:
            self.night_logs.append("场上没有爪牙。")
            self.public_night_logs.append("场上没有爪牙。")
        return False

    def night_mason(self) -> bool:
        """Runs Mason action. Returns False."""
        mason_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Mason"]
        self.public_night_logs.append("🛡️ 守夜人，请睁眼...")
        if len(mason_players) == 2:
            p1, p2 = mason_players
            self.players[p1].add_message("user", f"夜间睁眼，你看到了另一名守夜人伙伴 {self.players[p2].player_name}。")
            self.players[p2].add_message("user", f"夜间睁眼，你看到了另一名守夜人伙伴 {self.players[p1].player_name}。")
            self.night_logs.append(f"守夜人 【玩家 {p1}】 和 【玩家 {p2}】 确认了对方身份。")
            self.public_night_logs.append("守夜人们睁眼确认了伙伴。")
        elif len(mason_players) == 1:
            p_id = mason_players[0]
            self.players[p_id].add_message("user", "夜间睁眼，你没有看到其他守夜人，这说明另一张守夜人牌在中央牌堆。")
            self.night_logs.append(f"唯一在场的守夜人 【玩家 {p_id}】 睁眼，确认另一张守夜人牌在中央。")
            self.public_night_logs.append("守夜人睁眼，但场上只有一名守夜人。")
        else:
            self.night_logs.append("场上没有守夜人。")
            self.public_night_logs.append("场上没有守夜人。")
        return False

    def night_seer(self, action_data: dict = None) -> bool:
        """Runs Seer actions. Returns True if human Seer choice is needed."""
        seer_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Seer"]
        self.public_night_logs.append("👁️ 预言家，请睁眼并行动...")
        if seer_players:
            s_id = seer_players[0]
            seer = self.players[s_id]
            
            if seer.is_human:
                if action_data is None:
                    self.night_logs.append(f"预言家 【玩家 {s_id} (你)】 行动中，等待玩家选择...")
                    self.public_night_logs.append("预言家正在选择占卜目标...")
                    return True
            else:
                if config.LLM_DRIVEN_NIGHT_ACTIONS:
                    action_data = seer.query_night_action(SeerAction)
                else:
                    target_type = random.choice(["player", "center"])
                    if target_type == "player":
                        other_players = [i for i in range(1, self.player_count + 1) if i != s_id]
                        action_data = {"target_type": "player", "player_id": random.choice(other_players)}
                    else:
                        action_data = {"target_type": "center", "center_indices": random.sample([0, 1, 2], 2)}
            
            t_type = action_data.get("target_type", "center")
            if t_type == "player":
                target_id = action_data.get("player_id", 0)
                if target_id in self.players and target_id != s_id:
                    target_role = self.current_player_roles[target_id]
                    target_role_cn = self.roles_db[target_role]["name_cn"]
                    seer.add_message("user", f"你在夜间选择查看玩家 {target_id} 的身份。结果是：【{target_role_cn}】。")
                    self.night_logs.append(f"预言家 【玩家 {s_id}】 查看了玩家 {target_id} 的底牌，发现是：{target_role_cn}。")
                    self.public_night_logs.append(f"预言家睁眼，并选择查看了一名玩家的底牌。")
                else:
                    t_type = "center"  # fallback
                    
            if t_type == "center":
                indices = action_data.get("center_indices", [0, 1])
                if len(indices) < 2:
                    indices = [0, 1]
                idx1, idx2 = indices[0], indices[1]
                r1_cn = self.roles_db[self.current_center_cards[idx1]]["name_cn"]
                r2_cn = self.roles_db[self.current_center_cards[idx2]]["name_cn"]
                seer.add_message("user", f"你在夜间选择查看中央牌 {idx1} 和 中央牌 {idx2}。结果是：中央 {idx1} 为【{r1_cn}】，中央 {idx2} 为【{r2_cn}】。")
                self.night_logs.append(f"预言家 【玩家 {s_id}】 查看了中央牌 {idx1} ({r1_cn}) 和 中央牌 {idx2} ({r2_cn})。")
                self.public_night_logs.append(f"预言家睁眼，并选择查看了两张中央牌。")
        else:
            self.night_logs.append("场上没有预言家。")
            self.public_night_logs.append("场上没有预言家。")
        return False

    def night_robber(self, target_id: int = None) -> bool:
        """Runs Robber action. Returns True if human choice is needed."""
        robber_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Robber"]
        self.public_night_logs.append("💰 强盗，请睁眼并行动...")
        if robber_players:
            r_id = robber_players[0]
            robber = self.players[r_id]
            
            if robber.is_human:
                if target_id is None:
                    self.night_logs.append(f"强盗 【玩家 {r_id} (你)】 行动中，等待玩家选择交换目标...")
                    self.public_night_logs.append("强盗正在选择目标进行偷取...")
                    return True
            else:
                if config.LLM_DRIVEN_NIGHT_ACTIONS:
                    action_data = robber.query_night_action(RobberAction)
                    target_id = action_data.get("target_player_id", 0)
                else:
                    other_players = [i for i in range(1, self.player_count + 1) if i != r_id]
                    target_id = random.choice(other_players)
                    
            if target_id not in self.players or target_id == r_id:
                other_players = [i for i in range(1, self.player_count + 1) if i != r_id]
                target_id = random.choice(other_players)
                
            # Swap
            old_robber_card = self.current_player_roles[r_id]
            target_card = self.current_player_roles[target_id]
            self.current_player_roles[r_id] = target_card
            self.current_player_roles[target_id] = old_robber_card
            
            target_role_cn = self.roles_db[target_card]["name_cn"]
            robber.add_message(
                "user", 
                f"你在夜间拿走了玩家 {target_id} 的身份牌并与之交换，把你的强盗牌给了ta。你查看了新身份，你现在是：【{target_role_cn}】。"
            )
            self.night_logs.append(f"强盗 【玩家 {r_id}】 偷取了 【玩家 {target_id}】 的底牌，自身变成：{target_role_cn}。")
            self.public_night_logs.append(f"强盗睁眼，拿走并与之交换了一名玩家的身份牌。")
        else:
            self.night_logs.append("场上没有强盗。")
            self.public_night_logs.append("场上没有强盗。")
        return False

    def night_troublemaker(self, p1: int = None, p2: int = None) -> bool:
        """Runs Troublemaker action. Returns True if human choice is needed."""
        tm_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Troublemaker"]
        self.public_night_logs.append("😈 捣蛋鬼，请睁眼并行动...")
        if tm_players:
            t_id = tm_players[0]
            tm = self.players[t_id]
            
            if tm.is_human:
                if p1 is None or p2 is None:
                    self.night_logs.append(f"捣蛋鬼 【玩家 {t_id} (你)】 行动中，等待选择交换的两个玩家...")
                    self.public_night_logs.append("捣蛋鬼正在选择两位玩家以交换他们的卡牌...")
                    return True
            else:
                if config.LLM_DRIVEN_NIGHT_ACTIONS:
                    action_data = tm.query_night_action(TroublemakerAction)
                    p1 = action_data.get("player_id_1", 0)
                    p2 = action_data.get("player_id_2", 0)
                else:
                    other_players = [i for i in range(1, self.player_count + 1) if i != t_id]
                    p1, p2 = random.sample(other_players, 2)
                    
            if p1 == p2 or p1 not in self.players or p2 not in self.players or p1 == t_id or p2 == t_id:
                other_players = [i for i in range(1, self.player_count + 1) if i != t_id]
                p1, p2 = random.sample(other_players, 2)
                
            # Swap
            card1 = self.current_player_roles[p1]
            card2 = self.current_player_roles[p2]
            self.current_player_roles[p1] = card2
            self.current_player_roles[p2] = card1
            
            tm.add_message("user", f"你在夜间成功交换了玩家 {p1} 和玩家 {p2} 的身份牌（你并未查看卡牌内容）。")
            self.night_logs.append(f"捣蛋鬼 【玩家 {t_id}】 交换了 【玩家 {p1}】 和 【玩家 {p2}】 的牌。")
            self.public_night_logs.append("捣蛋鬼睁眼，暗中交换了另外两位玩家的身份牌。")
        else:
            self.night_logs.append("场上没有捣蛋鬼。")
            self.public_night_logs.append("场上没有捣蛋鬼。")
        return False

    def night_drunk(self, center_idx: int = None) -> bool:
        """Runs Drunk action. Returns True if human choice is needed."""
        drunk_players = [p_id for p_id, role in self.original_player_roles.items() if role == "Drunk"]
        self.public_night_logs.append("🍺 酒鬼，请睁眼并行动...")
        if drunk_players:
            d_id = drunk_players[0]
            drunk = self.players[d_id]
            
            if drunk.is_human:
                if center_idx is None:
                    self.night_logs.append(f"酒鬼 【玩家 {d_id} (你)】 行动中，等待选择一张中央牌...")
                    self.public_night_logs.append("酒鬼正在选择一张中央牌以进行闭眼交换...")
                    return True
            else:
                if config.LLM_DRIVEN_NIGHT_ACTIONS:
                    action_data = drunk.query_night_action(DrunkAction)
                    center_idx = action_data.get("center_index", 0)
                else:
                    center_idx = random.randint(0, 2)
                    
            center_idx = max(0, min(2, center_idx))
            
            # Swap own card with center card
            drunk_card = self.current_player_roles[d_id]
            center_card = self.current_center_cards[center_idx]
            self.current_player_roles[d_id] = center_card
            self.current_center_cards[center_idx] = drunk_card
            
            drunk.add_message("user", f"你在夜间将你自己的身份牌与中央牌 {center_idx} 进行了交换（你未查看新牌内容）。")
            self.night_logs.append(f"酒鬼 【玩家 {d_id}】 将自己的牌换成了中央牌 {center_idx}。")
            self.public_night_logs.append("酒鬼睁眼，暗中拿自己的牌与一张中央牌进行了闭眼交换。")
        else:
            self.night_logs.append("场上没有酒鬼。")
            self.public_night_logs.append("场上没有酒鬼。")
        return False

    # ----------------- DAY DISCUSSION PHASE -----------------

    def format_discussion_so_far(self) -> str:
        """Formats the public dialogue history for presentation to players."""
        return "\n".join(self.public_discussion_log)

    def run_day_speaking_turn(self, p_id: int, round_num: int):
        """Orchestration step for a single player's speech in a round."""
        player = self.players[p_id]
        context_str = self.format_discussion_so_far()
        
        # Human speaking is managed by UI, this function is only called for AI
        thought, statement = player.generate_day_statement(context_str)
            
        # Log thought privately
        self.private_thoughts[p_id].append(f"轮次 {round_num}: {thought}")
        
        # Save to player history
        player.add_message("user", f"第 {round_num} 轮发言，目前的公共讨论记录：\n{context_str}\n\n轮到你发言。")
        player.add_message("model", statement)
        
        return statement

    def run_voting_step_ai_only(self, human_id: int = None, human_vote: int = None, human_thought: str = "") -> dict:
        """Runs the simultaneous voting for all AI players. Combines it with human input if applicable."""
        votes = {}
        thoughts = {}
        
        # Handle human vote if play mode
        if human_id is not None:
            votes[human_id] = human_vote
            thoughts[human_id] = human_thought
            
        # Query all AI players
        discussion_log = self.format_discussion_so_far()
        for p_id, player in self.players.items():
            if p_id == human_id:
                continue
            thought, target = player.query_vote(discussion_log)
            votes[p_id] = target
            thoughts[p_id] = thought
            
        # Count votes
        tally = {i: 0 for i in range(1, self.player_count + 1)}
        for voter, target in votes.items():
            tally[target] += 1
            
        # Determine max votes
        max_votes = max(tally.values())
        
        eliminated_players = []
        if max_votes > 1:
            eliminated_players = [p_id for p_id, count in tally.items() if count == max_votes]
        else:
            eliminated_players = []
            
        result = {
            "votes": votes,
            "thoughts": thoughts,
            "tally": tally,
            "eliminated": eliminated_players,
            "max_votes": max_votes
        }
        return result

    def evaluate_winner(self, vote_result: dict) -> tuple[str, list[dict]]:
        """Evaluates who wins the game based on the current state and eliminated players."""
        eliminated_ids = vote_result["eliminated"]
        
        # Find where werewolves are currently (current roles)
        current_werewolves = [p_id for p_id, role in self.current_player_roles.items() if role == "Werewolf"]
        
        eliminated_roles_cn = []
        eliminated_werewolf_killed = False
        
        for p_id in eliminated_ids:
            role = self.current_player_roles[p_id]
            role_cn = self.roles_db[role]["name_cn"]
            eliminated_roles_cn.append({"player": p_id, "role": role_cn, "card_id": role})
            if role == "Werewolf":
                eliminated_werewolf_killed = True

        winner = ""
        reason = ""

        if not current_werewolves:
            # No wolves in play (they are all in the center)
            if len(eliminated_ids) == 0:
                winner = "Villager"
                reason = "场上没有狼人，且大家成功达成了平票没有处决任何人。村民阵营胜利！"
            else:
                winner = "Werewolf"
                reason = f"场上没有狼人，但大家投票处决了 【玩家 {eliminated_ids}】。村民阵营误杀无辜，狼人阵营胜利！"
        else:
            # Wolves are in play
            if eliminated_werewolf_killed:
                winner = "Villager"
                reason = f"成功处决了狼人（被处决的玩家是：{', '.join([f'玩家 {x['player']} ({x['role']})' for x in eliminated_roles_cn])}）。村民阵营胜利！"
            else:
                if len(eliminated_ids) == 0:
                    winner = "Werewolf"
                    reason = "场上有狼人，但大家达成了平票，没有处决任何人。狼人逃脱，狼人阵营胜利！"
                else:
                    winner = "Werewolf"
                    reason = f"没有处决任何狼人（被处决的玩家是：{', '.join([f'玩家 {x['player']} ({x['role']})' for x in eliminated_roles_cn])}）。狼人安全逃脱，狼人阵营胜利！"

        return winner, reason, eliminated_roles_cn
