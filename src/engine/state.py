"""游戏状态数据结构。"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class Role(Enum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    FOOL = "fool"
    VILLAGER = "villager"


class Faction(Enum):
    GOOD = "good"
    WOLF = "wolf"


class Phase(Enum):
    """游戏阶段枚举。"""
    NIGHT_WOLF = auto()       # 狼人睁眼
    NIGHT_WITCH = auto()      # 女巫睁眼
    NIGHT_SEER = auto()       # 预言家睁眼
    NIGHT_HUNTER = auto()     # 猎人确认状态
    NIGHT_FOOL = auto()       # 白痴确认身份（仅首夜）
    DAY_ANNOUNCE = auto()     # 天亮通报死讯
    DAY_ELECTION = auto()     # 警长竞选
    DAY_SPEECH = auto()       # 发言阶段
    DAY_VOTE = auto()         # 投票放逐
    DAY_PK_SPEECH = auto()    # 平票 PK 发言
    DAY_PK_VOTE = auto()      # 平票 PK 投票
    GAME_OVER = auto()        # 游戏结束


def role_faction(role: Role) -> Faction:
    """返回角色所属阵营。"""
    if role == Role.WEREWOLF:
        return Faction.WOLF
    return Faction.GOOD


def role_team(role: Role) -> str:
    """返回角色所属阵营名称。"""
    return "wolf" if role == Role.WEREWOLF else "good"


@dataclass
class Player:
    """玩家状态。"""
    player_id: int
    role: Role
    alive: bool = True
    has_vote: bool = True
    # 技能状态
    witch_save_available: bool = False
    witch_poison_available: bool = False
    witch_knows_dead: bool = False      # 解药用完前可见死者，用完后再 false
    hunter_can_shoot: bool = False
    fool_revealed: bool = False         # 白痴翻牌

    @property
    def faction(self) -> Faction:
        return role_faction(self.role)

    @property
    def is_good(self) -> bool:
        return self.faction == Faction.GOOD


@dataclass
class GameState:
    """完整游戏状态，贯穿整个游戏生命周期。"""
    players: list[Player] = field(default_factory=list)
    round: int = 0
    phase: Phase = Phase.NIGHT_WOLF
    turn: int = 1           # 大回合数（一轮白天+黑夜）

    # 警长相关
    sheriff_id: Optional[int] = None
    sheriff_elected: bool = False

    # 夜晚结果
    wolf_target: Optional[int] = None       # 狼人击杀目标
    witch_saved: Optional[int] = None       # 女巫解救的目标
    witch_poisoned: Optional[int] = None    # 女巫毒杀的目标
    seer_checked: Optional[int] = None      # 预言家查验目标
    seer_result: Optional[bool] = None      # True=好人, False=狼人

    # 白天结果
    vote_result: dict[int, int] = field(default_factory=dict)    # {target_id: vote_count}
    eliminated_today: Optional[int] = None   # 今天被放逐的玩家
    pk_candidates: list[int] = field(default_factory=list)      # 平票 PK 候选人

    # 发言顺序
    speech_order: list[int] = field(default_factory=list)
    current_speaker: Optional[int] = None
    speech_direction: str = ""              # "left" or "right", 相对于当前 speaker

    # 游戏日志（事件流）
    public_log: list[str] = field(default_factory=list)
    private_logs: dict[int, list[str]] = field(default_factory=dict)  # {player_id: [msg]}

    # 获胜方
    winner: Optional[Faction] = None

    def get_player(self, player_id: int) -> Optional[Player]:
        for p in self.players:
            if p.player_id == player_id:
                return p
        return None

    def get_alive_players(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    def get_alive_by_faction(self, faction: Faction) -> list[Player]:
        return [p for p in self.players if p.alive and p.faction == faction]

    def get_alive_by_role(self, role: Role) -> list[Player]:
        return [p for p in self.players if p.alive and p.role == role]

    def get_alive_ids(self) -> list[int]:
        return [p.player_id for p in self.players if p.alive]

    def get_voters(self) -> list[Player]:
        """获取所有有投票权的存活玩家。"""
        return [p for p in self.players if p.alive and p.has_vote]

    def get_wolves(self) -> list[Player]:
        return [p for p in self.players if p.role == Role.WEREWOLF]

    def get_alive_wolves(self) -> list[Player]:
        return [p for p in self.players if p.alive and p.role == Role.WEREWOLF]

    def add_public_log(self, msg: str):
        self.public_log.append(msg)

    def add_private_log(self, player_id: int, msg: str):
        if player_id not in self.private_logs:
            self.private_logs[player_id] = []
        self.private_logs[player_id].append(msg)

    def kill_player(self, player_id: int, cause: str = ""):
        """标记玩家死亡。"""
        player = self.get_player(player_id)
        if player:
            player.alive = False
            log_msg = f"玩家 {player_id} 死亡"
            if cause:
                log_msg += f"（{cause}）"
            self.add_public_log(log_msg)
