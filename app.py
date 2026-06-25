# app.py
import streamlit as st
import random
import time
import os
import config
from game_engine import OneNightEngine

st.set_page_config(page_title="🐺 一夜终极狼人 LLM 游戏室", layout="centered")

# Set up page headers
st.title("🐺 一夜狼人 · LLM 智能对决")
st.caption("基于 Gemini 3.5 Flash 与 Streamlit 的大模型狼人杀游戏")

# Check for API Key
if "GEMINI_API_KEY" not in os.environ:
    st.warning("⚠️ 检测到未设置环境变量 `GEMINI_API_KEY`。请在后台环境中设置此变量，或在下方临时输入以启动游戏：")
    temp_key = st.text_input("Gemini API Key:", type="password")
    if temp_key:
        os.environ["GEMINI_API_KEY"] = temp_key

# Initialize Engine
if "engine" not in st.session_state:
    st.session_state.engine = OneNightEngine()

# Initialize session state variables
if "game_state" not in st.session_state:
    st.session_state.game_state = {
        "stage": "setup",
        "human_id": None,
        "round": 1,
        "speaker_idx": 0,
        "speaking_order": [],
        "night_step": 0,  # 0:werewolf, 1:minion, 2:mason, 3:seer, 4:robber, 5:troublemaker, 6:drunk, 7:done, 8:button
        "vote_result": None,
        "mode": "Simulation", # "Simulation" or "Play"
        "has_spoken": False,
        "current_statement": ""
    }

def restart_game():
    st.session_state.engine = OneNightEngine()
    st.session_state.game_state = {
        "stage": "setup",
        "human_id": None,
        "round": 1,
        "speaker_idx": 0,
        "speaking_order": [],
        "night_step": 0,
        "vote_result": None,
        "mode": st.session_state.game_state["mode"],
        "has_spoken": False,
        "current_statement": ""
    }

# ----------------- UI CONTROLS (SETUP) -----------------
if st.session_state.game_state["stage"] == "setup":
    st.write("欢迎来到【一夜终极狼人】智能对决！本局共有 6 名玩家与 3 张中央底牌。")
    
    # Select Game Mode
    mode = st.radio("选择游戏模式：", ["🤖 纯 AI 模拟对局 (观察者模式)", "🎮 亲自参与游戏 (玩家模式)"])
    
    human_id = None
    if mode == "🎮 亲自参与游戏 (玩家模式)":
        human_id = st.selectbox("选择你的玩家 ID (你可以扮演玩家 1 至 6)：", list(range(1, 7)), index=0)
        st.session_state.game_state["mode"] = "Play"
    else:
        st.session_state.game_state["mode"] = "Simulation"
        
    temp = st.slider("模型创意温度 (Temperature) - 越高发言越狡猾多变：", 0.5, 1.2, 0.8, 0.05)
    config.DEFAULT_TEMP = temp
    
    llm_night = st.checkbox("大模型自主进行夜间行动 (若取消勾选，则 AI 玩家将进行随机行动)", value=True)
    config.LLM_DRIVEN_NIGHT_ACTIONS = llm_night
    
    if st.button("🚀 开始游戏", use_container_width=True):
        st.session_state.game_state["human_id"] = human_id
        st.session_state.engine.setup_game(human_player_id=human_id)
        
        # Determine randomized speaking order starting from a random index S, then wrapping around
        start_idx = random.randint(1, 6)
        order = [((start_idx - 1 + i) % 6) + 1 for i in range(6)]
        st.session_state.game_state["speaking_order"] = order
        st.session_state.game_state["stage"] = "night"
        st.session_state.game_state["night_step"] = 0
        st.rerun()

# ----------------- GAME STATE ACTIONS -----------------
engine = st.session_state.engine
gs = st.session_state.game_state

# Helper: check if current role is human
def is_role_human(role_name: str) -> bool:
    if gs["human_id"] is None:
        return False
    return engine.original_player_roles[gs["human_id"]] == role_name

# ----------------- NIGHT PHASE -----------------
if gs["stage"] == "night":
    st.subheader("🌙 夜间行动阶段")
    
    # Display the public night logs so far (anti-spoiler)
    for log in engine.public_night_logs:
        st.write(log)
        
    step = gs["night_step"]
    
    # 0. Werewolf Step (狼人)
    if step == 0:
        werewolves = [p_id for p_id, role in engine.original_player_roles.items() if role == "Werewolf"]
        if len(werewolves) == 1 and werewolves[0] == gs["human_id"]:
            # Human lone wolf choice
            st.info("🐺 你是场上唯一的独狼。请选择你要查看的一张中央底牌：")
            center_choice = st.radio("中央牌选择：", [0, 1, 2], horizontal=True)
            if st.button("确认查看"):
                engine.night_werewolf(center_choice=center_choice)
                gs["night_step"] = 1
                st.rerun()
        else:
            # AI lone wolf, 2 wolves, or 0 wolves
            engine.night_werewolf()
            gs["night_step"] = 1
            st.rerun()
            
    # 1. Minion Step (爪牙)
    elif step == 1:
        engine.night_minion()
        gs["night_step"] = 2
        st.rerun()
        
    # 2. Mason Step (守夜人)
    elif step == 2:
        engine.night_mason()
        gs["night_step"] = 3
        st.rerun()
        
    # 3. Seer Step (预言家)
    elif step == 3:
        seer_players = [p_id for p_id, role in engine.original_player_roles.items() if role == "Seer"]
        if not seer_players:
            engine.night_seer() # Logs "场上没有预言家"
            gs["night_step"] = 4
            st.rerun()
        else:
            s_id = seer_players[0]
            if s_id == gs["human_id"]:
                st.info("👁️ 你是【预言家】。请选择你的夜间行动：")
                t_type = st.radio("查看类型：", ["查看一名玩家底牌", "查看两张中央牌"])
                if t_type == "查看一名玩家底牌":
                    target_player = st.selectbox("选择玩家：", [i for i in range(1, 7) if i != gs["human_id"]])
                    if st.button("确认行动"):
                        action_data = {"target_type": "player", "player_id": target_player}
                        engine.night_seer(action_data=action_data)
                        gs["night_step"] = 4
                        st.rerun()
                else:
                    target_center = st.multiselect("选择两张中央牌 (必须且只能选2个)：", [0, 1, 2], default=[0, 1])
                    if st.button("确认行动"):
                        if len(target_center) != 2:
                            st.error("请选择正好 2 张中央牌！")
                        else:
                            action_data = {"target_type": "center", "center_indices": target_center}
                            engine.night_seer(action_data=action_data)
                            gs["night_step"] = 4
                            st.rerun()
            else:
                engine.night_seer()
                gs["night_step"] = 4
                st.rerun()

    # 4. Robber Step (强盗)
    elif step == 4:
        robber_players = [p_id for p_id, role in engine.original_player_roles.items() if role == "Robber"]
        if not robber_players:
            engine.night_robber() # Logs "场上没有强盗"
            gs["night_step"] = 5
            st.rerun()
        else:
            r_id = robber_players[0]
            if r_id == gs["human_id"]:
                st.info("💰 你是【强盗】。请选择你要偷取并与之交换卡牌的玩家：")
                target_player = st.selectbox("选择目标玩家：", [i for i in range(1, 7) if i != gs["human_id"]])
                if st.button("交换并查看身份"):
                    engine.night_robber(target_id=target_player)
                    gs["night_step"] = 5
                    st.rerun()
            else:
                engine.night_robber()
                gs["night_step"] = 5
                st.rerun()
            
    # 5. Troublemaker Step (捣蛋鬼)
    elif step == 5:
        tm_players = [p_id for p_id, role in engine.original_player_roles.items() if role == "Troublemaker"]
        if not tm_players:
            engine.night_troublemaker() # Logs "场上没有捣蛋鬼"
            gs["night_step"] = 6
            st.rerun()
        else:
            t_id = tm_players[0]
            if t_id == gs["human_id"]:
                st.info("😈 你是【捣蛋鬼】。请选择你想要秘密交换底牌的另外两名玩家 (不能是自己)：")
                targets = st.multiselect("选择两名玩家：", [i for i in range(1, 7) if i != gs["human_id"]], max_selections=2)
                if st.button("悄悄交换两张牌"):
                    if len(targets) != 2:
                        st.error("请正好选择 2 张牌进行交换！")
                    else:
                        engine.night_troublemaker(p1=targets[0], p2=targets[1])
                        gs["night_step"] = 6
                        st.rerun()
            else:
                engine.night_troublemaker()
                gs["night_step"] = 6
                st.rerun()

    # 6. Drunk Step (酒鬼)
    elif step == 6:
        drunk_players = [p_id for p_id, role in engine.original_player_roles.items() if role == "Drunk"]
        if not drunk_players:
            engine.night_drunk() # Logs "场上没有酒鬼"
            gs["night_step"] = 7
            st.rerun()
        else:
            d_id = drunk_players[0]
            if d_id == gs["human_id"]:
                st.info("🍺 你是【酒鬼】。请选择一张你要在中央牌堆中秘密交换的底牌 (你无法知道这张新牌的角色)：")
                center_idx = st.radio("选择中央牌：", [0, 1, 2], horizontal=True)
                if st.button("闭眼摸牌交换"):
                    engine.night_drunk(center_idx=center_idx)
                    gs["night_step"] = 7
                    st.rerun()
            else:
                engine.night_drunk()
                gs["night_step"] = 7
                st.rerun()
            
    # 7. Night Logs Finalization
    elif step == 7:
        engine.public_night_logs.append("🌅 天亮了，所有玩家请睁眼！开始讨论。")
        gs["night_step"] = 8
        st.rerun()
        
    elif step == 8:
        if st.button("🌅 睁眼，开始白天讨论"):
            gs["stage"] = "day_speaking"
            gs["round"] = 1
            gs["speaker_idx"] = 0
            st.rerun()

# ----------------- DAY DISCUSSION PHASE -----------------
elif gs["stage"] == "day_speaking":
    st.subheader(f"💬 白天讨论发言阶段 - 第 {gs['round']} / 3 轮")
    
    # Persistent Public Night Log
    with st.expander("📁 昨晚公共行动简报 (无剧透)", expanded=False):
        for log in engine.public_night_logs:
            st.write(log)
            
    # Display the conversation log
    for line in engine.public_discussion_log:
        st.text(line)
        
    speaker_order = gs["speaking_order"]
    idx = gs["speaker_idx"]
    round_num = gs["round"]
    
    # Show speaking order indicator
    st.caption(f"发言顺序：{' → '.join([f'玩家 {x}' for x in speaker_order])}")
    
    if idx < 6:
        active_speaker = speaker_order[idx]
        player = engine.players[active_speaker]
        
        if player.is_human:
            # Human player's turn to speak
            st.success(f"👉 轮到你 【玩家 {active_speaker}】 发言了！")
            
            with st.container():
                # Provide a secret expander for the user to see their initial role and night action logs
                with st.expander("👁️ 查看你的秘密信息", expanded=False):
                    role_cn = engine.roles_db[player.initial_role]["name_cn"]
                    st.write(f"你的初始身份是：**{role_cn}**")
                    st.write("你的夜间消息：")
                    # Display messages containing night results (usually the last user messages)
                    for m in player.history:
                        if m.role == "user" and ("夜间" in m.parts[0].text or "你在夜间" in m.parts[0].text):
                            st.write(f"- {m.parts[0].text}")
                            
                # Speech Inputs
                thought_input = st.text_area("内心真实想法 (不会向其他玩家公开)：", placeholder="例如：我是真强盗，我偷了玩家3的狼人牌，所以我现在是狼人，我要保护玩家3，装作村民...")
                statement_input = st.text_input("公开言论 (向所有人宣布)：", placeholder="例如：我是预言家，我昨天看了中央牌...")
                
                if st.button("发表言论"):
                    if not statement_input:
                        st.error("公开言论不能为空！")
                    else:
                        # Save inputs
                        engine.private_thoughts[active_speaker].append(f"轮次 {round_num}: {thought_input}")
                        prefix = f"【玩家 {active_speaker} (你)】 说："
                        full_statement = f"{prefix}\"{statement_input}\""
                        engine.public_discussion_log.append(full_statement)
                        
                        player.add_message("user", f"第 {round_num} 轮发言，目前的公共讨论记录：\n{engine.format_discussion_so_far()}\n\n轮到你发言。")
                        player.add_message("model", statement_input)
                        
                        # Advance speaker index
                        gs["speaker_idx"] += 1
                        st.rerun()
        else:
            # LLM player turn to speak
            if not gs.get("has_spoken", False):
                st.info(f"⏳ 正在等待 【玩家 {active_speaker}】 思考并组织语言...")
                with st.spinner("思考中..."):
                    statement = engine.run_day_speaking_turn(active_speaker, round_num)
                    gs["current_statement"] = statement
                    gs["has_spoken"] = True
                    st.rerun()
            else:
                statement = gs.get("current_statement", "")
                
                # Typewriter animation
                prefix = f"【玩家 {active_speaker}】 说："
                st.write(prefix)
                
                def stream_char():
                    for char in f"\"{statement}\"":
                        yield char
                        time.sleep(0.02)
                st.write_stream(stream_char)
                
                # Log statement publicly in session log
                full_statement = f"{prefix}\"{statement}\""
                engine.public_discussion_log.append(full_statement)
                
                # Reset turn state and advance
                gs["has_spoken"] = False
                gs["current_statement"] = ""
                gs["speaker_idx"] += 1
                st.rerun()
    else:
        # All players have spoken in this round
        gs["speaker_idx"] = 0
        gs["round"] += 1
        if gs["round"] == 4:
            # Move to voting after 3 rounds
            gs["stage"] = "voting"
        st.rerun()

# ----------------- VOTING PHASE -----------------
elif gs["stage"] == "voting":
    st.subheader("🗳️ 投票淘汰阶段")
    st.write("白天的讨论已经结束。请各位玩家写下内心想法，并投出你神圣的一票。")
    
    # Persistent Public Night Log
    with st.expander("📁 昨晚公共行动简报 (无剧透)", expanded=False):
        for log in engine.public_night_logs:
            st.write(log)
            
    # Display the complete discussion log
    with st.expander("显示完整对话记录以供查阅"):
        for line in engine.public_discussion_log:
            st.text(line)

    human_id = gs["human_id"]
    if human_id is not None:
        # Human player vote
        st.success("🗳️ 轮到你投票了！")
        vote_thought = st.text_area("你的内心投票动机、最后的推理逻辑 (不公开)：")
        vote_target = st.selectbox("选择你投票淘汰的玩家：", list(range(1, 7)), format_func=lambda x: f"玩家 {x}（包括自己）")
        
        if st.button("确认投票"):
            with st.spinner("AI 玩家正在秘密投票中..."):
                vote_result = engine.run_voting_step_ai_only(
                    human_id=human_id,
                    human_vote=vote_target,
                    human_thought=vote_thought
                )
                
                # Check winner
                winner, reason, eliminated_roles_cn = engine.evaluate_winner(vote_result)
                vote_result["winner"] = winner
                vote_result["reason"] = reason
                vote_result["eliminated_roles"] = eliminated_roles_cn
                
                gs["vote_result"] = vote_result
                gs["stage"] = "ended"
                st.rerun()
    else:
        # Pure simulation mode voting (all AI)
        if st.button("🗳️ 收集 AI 玩家投票"):
            with st.spinner("AI 玩家正在秘密投票中..."):
                vote_result = engine.run_voting_step_ai_only()
                
                winner, reason, eliminated_roles_cn = engine.evaluate_winner(vote_result)
                vote_result["winner"] = winner
                vote_result["reason"] = reason
                vote_result["eliminated_roles"] = eliminated_roles_cn
                
                gs["vote_result"] = vote_result
                gs["stage"] = "ended"
                st.rerun()

# ----------------- GAME OVER / RESULTS -----------------
elif gs["stage"] == "ended":
    st.subheader("🏁 游戏结束 · 结算面板")
    
    vr = gs["vote_result"]
    
    # 1. Announce Winner
    if vr["winner"] == "Villager":
        st.balloons()
        st.success(f"🎉 胜利阵营：村民阵营！\n\n{vr['reason']}")
    else:
        st.error(f"💀 胜利阵营：狼人阵营！\n\n{vr['reason']}")
        
    # 2. Voting Tally Table
    st.write("📊 **投票明细**")
    tally_data = []
    for p_id in range(1, 7):
        target = vr["votes"][p_id]
        vote_count = vr["tally"][p_id]
        voter_name = f"玩家 {p_id}" + (" (你)" if p_id == gs["human_id"] else "")
        target_name = f"玩家 {target}" + (" (你)" if target == gs["human_id"] else "")
        tally_data.append({
            "投票人": voter_name,
            "投给目标": target_name,
            "自身得票数": vote_count
        })
    st.table(tally_data)

    # 3. Eliminated Players
    if vr["eliminated"]:
        elim_str = ", ".join([f"玩家 {x['player']} ({x['role']})" for x in vr["eliminated_roles"]])
        st.write(f"💀 **被淘汰的玩家**：{elim_str}")
    else:
        st.write("🕊️ **被淘汰的玩家**：无人被淘汰 (平票，所有人均得1票)")

    # 4. Identity Reveal
    st.write("🃏 **身份揭晓 (全场明牌)**")
    
    reveal_data = []
    for p_id in range(1, 7):
        orig_role = engine.original_player_roles[p_id]
        curr_role = engine.current_player_roles[p_id]
        orig_cn = engine.roles_db[orig_role]["name_cn"]
        curr_cn = engine.roles_db[curr_role]["name_cn"]
        
        status_suffix = ""
        if p_id in vr["eliminated"]:
            status_suffix = " 💀 (被淘汰)"
            
        p_name = f"玩家 {p_id}" + (" (你)" if p_id == gs["human_id"] else "") + status_suffix
        reveal_data.append({
            "玩家": p_name,
            "初始底牌": orig_cn,
            "当前真实底牌": curr_cn
        })
    st.table(reveal_data)
    
    # 5. Center Cards Reveal
    st.write("🃏 **中央牌底牌**")
    for idx, (orig, curr) in enumerate(zip(engine.original_center_cards, engine.current_center_cards)):
        orig_cn = engine.roles_db[orig]["name_cn"]
        curr_cn = engine.roles_db[curr]["name_cn"]
        st.write(f"- 中央牌 {idx}：初始是【{orig_cn}】，当前是【{curr_cn}】")

    # 6. Spoilers: Night Action Log
    with st.expander("📁 查阅完整的夜间行动日志 (含绝密信息)"):
        for log in engine.night_logs:
            st.write(log)

    # 7. Spoilers: Players' Private Thoughts
    with st.expander("🧠 查阅大模型玩家的内心心理日志 (Private Thoughts)"):
        for p_id in range(1, 7):
            p_name = f"玩家 {p_id}" + (" (你)" if p_id == gs["human_id"] else "")
            st.write(f"**{p_name} 的内心独白：**")
            
            # Show round thoughts
            for thought in engine.private_thoughts[p_id]:
                st.write(f"- {thought}")
            # Show vote thought
            st.write(f"- 投票动机: {vr['thoughts'][p_id]}")
            st.divider()

    # Restart button
    if st.button("🔄 再来一局", use_container_width=True):
        restart_game()
        st.rerun()
