
基于我对 SparrowRecSys 项目架构和设计文档的详细分析，现在为您提供完整的**游戏推荐系统技术方案和开发计划**：

---

# 🎮 游戏推荐系统技术方案与开发计划

## 一、项目概述

### 1.1 项目背景

基于 SparrowRecSys 项目架构思想，结合 Casino 推荐系统设计文档，构建一个**全 Python 技术栈**的游戏推荐系统。系统采用经典的四层漏斗架构（召回→粗排→精排→重排），支持快速迭代和 MVP 交付。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **简单优先** | 先跑通完整链路，再优化各环节 |
| **Python 统一** | 全栈使用 Python，降低维护成本 |
| **分层解耦** | 召回/排序/服务层独立，支持独立迭代 |
| **渐进增强** | MVP 先上线，后续按需增加高级特性 |

---

## 二、系统架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           用户请求层                                  │
│     Web/App  →  Nginx/API Gateway  →  Recommendation API            │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      推荐服务层 (FastAPI)                             │
│  ┌──────────┬──────────┬──────────┬──────────┬───────────────────┐ │
│  │ 召回模块  │ 粗排模块  │ 精排模块  │ 重排模块  │  冷启动/业务策略  │ │
│  │ ~500候选 │ ~150候选  │ ~50候选  │ ~20结果  │                   │ │
│  └──────────┴──────────┴──────────┴──────────┴───────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         数据存储层                                    │
│  ┌──────────┬──────────┬──────────┬──────────────────────────────┐ │
│  │  Redis   │  MySQL   │  FAISS   │       特征存储 (Redis)        │ │
│  │ (缓存)   │ (业务DB) │(向量索引) │                              │ │
│  └──────────┴──────────┴──────────┴──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      离线计算层 (Python)                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  特征工程 (PySpark)  │  模型训练 (PyTorch)  │  定时任务 (Celery)  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 四层漏斗设计

| 层级 | 输入规模 | 输出规模 | 延迟目标 | 模型复杂度 |
|------|----------|----------|----------|------------|
| **召回层** | 全量游戏库 (~200) | ~50 | <10ms | 简单/规则+向量 |
| **粗排层** | ~50 | ~30 | <10ms | 轻量双塔 |
| **精排层** | ~30 | ~15 | <30ms | DeepFM/DIN |
| **重排层** | ~15 | ~10 | <5ms | 规则+多样性 |

### 2.3 简化策略（相比原文档）

考虑到**快速开发和 MVP 交付**需求，对原设计进行以下简化：

| 原设计 | 简化方案 | 理由 |
|--------|----------|------|
| 6路召回 | 4路召回 (热门+Item-CF+内容+新游戏) | 足够覆盖主要场景 |
| Kafka+Flink 实时特征 | Redis + 定时任务 | 降低运维复杂度 |
| Triton Inference | TorchServe 或直接 FastAPI 推理 | Python 原生更简单 |
| MySQL+HBase | MySQL + Redis | 单一数据库简化运维 |
| 复杂的 DIEN/MMOE | DeepFM + 简化版 DIN | MVP 阶段足够 |

---

## 三、核心模块设计

### 3.1 召回模块设计（六路召回）

#### 3.1.1 召回架构总览

参考 SparrowRecSys 的多路召回设计，结合游戏推荐的特点，设计六路召回策略：

```
                         ┌─────────────────┐
                         │   用户请求      │
                         │   + 场景识别    │
                         └────────┬────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │      用户类型判断          │
                    │      新用户 / 活跃用户      │
                    └─────────────┬─────────────┘
                                  │
     ┌──────────┬──────────┬──────┴──────┬──────────┬──────────┐
     │          │          │             │          │          │
     ▼          ▼          ▼             ▼          ▼          ▼
┌────────┐┌────────┐┌────────────┐┌────────┐┌────────┐┌────────┐
│Item-CF ││Embedding││  内容召回   ││热门召回││新游戏  ││个性化  │
│(协同)  ││(向量)   ││(属性+标签) ││(多维度)││ 召回   ││ 召回   │
└───┬────┘└───┬────┘└─────┬──────┘└───┬────┘└───┬────┘└───┬────┘
    │         │           │           │         │         │
    │ 动态    │  动态     │  固定     │ 动态    │  固定   │ 动态
    │ 配额    │  配额     │  配额     │ 配额    │  配额   │ 配额
    └─────────┴───────────┴───────────┴─────────┴─────────┘
                                  │
                                  ▼
                       ┌─────────────────┐
                       │  召回合并去重    │
                       │   + 配额截断    │
                       │  (~100个候选)   │
                       └─────────────────┘
```

#### 3.1.2 召回配额分配策略

基于用户生命周期阶段，动态调整各路召回配额：

```python
# 召回策略设计 - 游戏推荐专用配额
RECALL_QUOTA = {
    "新用户": {           # 行为数 < 5
        "hot": 30,        # 热门召回：高权重，保证体验
        "content": 20,    # 内容召回：基于注册渠道/设备偏好
        "new_game": 15,   # 新游戏：增加探索
        "embedding": 10,  # Embedding：冷启动效果有限
        "itemcf": 0,      # Item-CF：无历史数据
        "personal": 0     # 个性化：无数据
    },
    "活跃用户": {         # 行为数 >= 5
        "hot": 15,        # 热门：降权，增加个性化
        "content": 15,    # 内容：稳定配额
        "new_game": 10,   # 新游戏：适度曝光
        "embedding": 25,  # Embedding：高权重
        "itemcf": 25,     # Item-CF：高权重
        "personal": 10    # 个性化：续玩/收藏
    },
}
```

#### 3.1.3 Item-CF 协同过滤召回（参考 SparrowRecSys 实现）

**核心原理：** 基于用户-物品交互矩阵，计算物品间相似度，为用户推荐与其历史偏好相似的游戏。

**游戏场景特化：**
- 游戏 Session 时长是重要权重因子（相比电影评分）
- 投注行为比点击行为更具参考价值
- 需要考虑游戏类目内/跨类目的相似性差异

```python
import math
from collections import defaultdict
from typing import List, Tuple, Dict, Set

class GameItemCFRecall:
    """
    游戏 Item-CF 召回
    参考 SparrowRecSys Embedding.scala 的协同过滤思想，
    针对游戏场景进行优化：
    1. 使用 IUF (Inverse User Frequency) 降低活跃用户权重
    2. 加入游戏时长作为隐式反馈权重
    3. 支持类目内/跨类目的相似度分别计算
    """

    def __init__(self):
        self.item_similarity: Dict[str, Dict[str, float]] = {}
        self.user_games: Dict[str, Set[str]] = {}
        self.game_categories: Dict[str, str] = {}

    def compute_similarity_matrix(
        self,
        interactions: List[Tuple[str, str, float, str]],  # (user_id, game_id, duration, category)
        top_k_similar: int = 50
    ):
        """
        计算游戏相似度矩阵

        相似度公式 (改进的余弦相似度 + IUF):
        sim(i,j) = Σ_u (w_u * duration_ui * duration_uj) / sqrt(|N(i)| * |N(j)|)

        其中 w_u = 1 / log(1 + |N(u)|) 是 IUF 权重，降低活跃用户的贡献
        """
        # Step 1: 构建用户-游戏倒排索引
        user_games = defaultdict(dict)  # {user: {game: duration}}
        game_users = defaultdict(set)   # {game: set(users)}
        game_categories = {}

        for user_id, game_id, duration, category in interactions:
            user_games[user_id][game_id] = duration
            game_users[game_id].add(user_id)
            game_categories[game_id] = category

        self.user_games = {u: set(games.keys()) for u, games in user_games.items()}
        self.game_categories = game_categories

        # Step 2: 计算相似度
        item_sim_scores = defaultdict(lambda: defaultdict(float))

        for user_id, games in user_games.items():
            game_list = list(games.keys())
            # IUF 权重：活跃用户贡献降低
            iuf_weight = 1.0 / math.log(1 + len(game_list))

            for i, game_i in enumerate(game_list):
                duration_i = games[game_i]
                for game_j in game_list[i+1:]:
                    duration_j = games[game_j]
                    # 时长加权的共现贡献
                    contribution = iuf_weight * math.sqrt(duration_i * duration_j)
                    item_sim_scores[game_i][game_j] += contribution
                    item_sim_scores[game_j][game_i] += contribution

        # Step 3: 归一化并截取 Top-K
        for game_i, related in item_sim_scores.items():
            norm_i = len(game_users[game_i])
            normalized = {}
            for game_j, score in related.items():
                norm_j = len(game_users[game_j])
                normalized[game_j] = score / math.sqrt(norm_i * norm_j)

            # 保留 Top-K 相似游戏
            sorted_items = sorted(normalized.items(), key=lambda x: -x[1])
            self.item_similarity[game_i] = dict(sorted_items[:top_k_similar])

    def recall(
        self,
        user_id: str,
        played_games: List[str],
        top_k: int = 50,
        filter_same_category: bool = False
    ) -> List[Tuple[str, float]]:
        """
        为用户召回游戏

        score(u, j) = Σ_{i∈N(u)} sim(i, j) * recency_weight(i)

        参数:
            filter_same_category: 是否只召回同类目游戏（分类页场景）
        """
        if not played_games:
            return []

        candidate_scores = defaultdict(float)
        played_set = set(played_games)

        # 时间衰减：最近玩的游戏权重更高
        for idx, game_id in enumerate(reversed(played_games[-20:])):  # 最近20个
            recency_weight = 1.0 / (1 + idx * 0.1)  # 越近权重越高

            similar_games = self.item_similarity.get(game_id, {})
            for sim_game_id, similarity in similar_games.items():
                if sim_game_id in played_set:
                    continue
                if filter_same_category:
                    if self.game_categories.get(sim_game_id) != self.game_categories.get(game_id):
                        continue
                candidate_scores[sim_game_id] += similarity * recency_weight

        ranked = sorted(candidate_scores.items(), key=lambda x: -x[1])
        return ranked[:top_k]
```

#### 3.1.4 Embedding 向量召回（参考 SparrowRecSys Item2Vec）

**核心原理：** 借鉴 Word2Vec 的思想，将用户的游戏序列视为"句子"，游戏ID视为"单词"，学习游戏的稠密向量表示。

**游戏场景特化：**
- 游戏 Session 通常较短（几分钟），序列构建需考虑时间窗口
- 加入游戏属性（category, provider, volatility）增强语义
- 支持跨类目的向量相似度计算

```python
from pyspark.mllib.feature import Word2Vec
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, collect_list, udf, array_join
from pyspark.sql.types import ArrayType, StringType
import numpy as np
import faiss

class GameEmbeddingRecall:
    """
    游戏 Embedding 召回
    参考 SparrowRecSys Embedding.py 的 Item2Vec 实现，
    针对游戏场景优化：
    1. 使用游戏 Session 序列而非评分序列
    2. 窗口大小适配游戏浏览特点（较短的浏览路径）
    3. 加入游戏属性增强 Embedding 语义
    """

    def __init__(self, embedding_dim: int = 64):
        self.embedding_dim = embedding_dim
        self.game_embeddings: Dict[str, np.ndarray] = {}
        self.faiss_index = None
        self.game_id_list: List[str] = []

    def process_game_sequences(self, spark: SparkSession, behavior_path: str):
        """
        处理用户行为数据，生成游戏序列

        参考 SparrowRecSys processItemSequence 函数：
        1. 读取用户行为日志
        2. 筛选有效行为（play/bet，时长>30秒）
        3. 按用户分组，时间排序，生成序列
        """
        behaviors = spark.read.parquet(behavior_path)

        # 自定义排序函数
        def sort_by_time(game_list, time_list):
            pairs = sorted(zip(game_list, time_list), key=lambda x: x[1])
            return [str(x[0]) for x in pairs]

        sort_udf = udf(sort_by_time, ArrayType(StringType()))

        # 数据处理流水线
        user_sequences = behaviors \
            .where((col("behavior_type").isin(["play", "bet"])) &
                   (col("duration") >= 30)) \
            .groupBy("user_id") \
            .agg(
                sort_udf(
                    collect_list("game_id"),
                    collect_list("created_at")
                ).alias("game_sequence")
            )

        return user_sequences.select("game_sequence").rdd.map(lambda x: x[0])

    def train_game2vec(self, spark: SparkSession, sequences_rdd, output_path: str):
        """
        训练 Game2Vec 模型

        参考 SparrowRecSys trainItem2vec 函数
        """
        word2vec = Word2Vec() \
            .setVectorSize(self.embedding_dim) \
            .setWindowSize(3) \
            .setNumIterations(15)
        # 游戏场景窗口设为3（比电影场景小，因为游戏浏览路径较短）

        model = word2vec.fit(sequences_rdd)

        # 保存 Embedding
        for game_id in model.getVectors().keys():
            vector = model.getVectors()[game_id]
            self.game_embeddings[game_id] = np.array(vector)

        # 构建 FAISS 索引
        self._build_faiss_index()

        return model

    def _build_faiss_index(self):
        """
        构建 FAISS 向量索引，用于高效近邻搜索

        参考 SparrowRecSys 的向量检索设计
        """
        self.game_id_list = list(self.game_embeddings.keys())
        embeddings = np.array([self.game_embeddings[gid] for gid in self.game_id_list])
        embeddings = embeddings.astype('float32')

        # L2 归一化（用于余弦相似度）
        faiss.normalize_L2(embeddings)

        # 对于小规模游戏库（<1000），使用精确搜索
        # 大规模时可改用 IndexIVFPQ
        self.faiss_index = faiss.IndexFlatIP(self.embedding_dim)
        self.faiss_index.add(embeddings)

    def recall(
        self,
        user_embedding: np.ndarray,
        top_k: int = 50,
        exclude_games: Set[str] = None
    ) -> List[Tuple[str, float]]:
        """
        基于用户 Embedding 的向量召回
        """
        if self.faiss_index is None:
            return []

        exclude_games = exclude_games or set()

        # 归一化用户向量
        user_vec = user_embedding.astype('float32').reshape(1, -1)
        faiss.normalize_L2(user_vec)

        # 多召回一些，用于过滤
        scores, indices = self.faiss_index.search(user_vec, top_k * 2)

        results = []
        for idx, score in zip(indices[0], scores[0]):
            if idx < 0:
                continue
            game_id = self.game_id_list[idx]
            if game_id not in exclude_games:
                results.append((game_id, float(score)))
            if len(results) >= top_k:
                break

        return results

    def compute_user_embedding(
        self,
        played_games: List[str],
        durations: List[float] = None
    ) -> np.ndarray:
        """
        计算用户 Embedding（聚合用户玩过的游戏 Embedding）

        参考 SparrowRecSys generateUserEmb 函数，加入时长加权
        """
        if not played_games:
            return np.zeros(self.embedding_dim)

        embeddings = []
        weights = []

        for i, game_id in enumerate(played_games):
            if game_id in self.game_embeddings:
                embeddings.append(self.game_embeddings[game_id])
                # 时长加权（如果提供）+ 时间衰减
                duration_weight = math.sqrt(durations[i]) if durations else 1.0
                recency_weight = 1.0 / (1 + (len(played_games) - i) * 0.05)
                weights.append(duration_weight * recency_weight)

        if not embeddings:
            return np.zeros(self.embedding_dim)

        # 加权平均
        weights = np.array(weights) / sum(weights)
        user_emb = np.average(embeddings, axis=0, weights=weights)

        return user_emb
```

#### 3.1.5 内容召回（游戏属性匹配）

**游戏特有属性：** category, provider, RTP, volatility, themes, features

```python
class GameContentRecall:
    """
    游戏内容召回：基于用户偏好与游戏属性匹配

    游戏特有维度：
    - category: Slots/Crash/Live/Virtual
    - provider: Pragmatic Play/Spribe/Evolution
    - volatility: high/medium/low（风险偏好）
    - themes: mythology/animal/adventure/asian
    - features: megaways/free_spins/bonus_buy
    - rtp: 返还率区间
    """

    def __init__(self, redis_client):
        self.redis = redis_client

    async def recall(
        self,
        user_profile: dict,
        top_k: int = 30,
        exclude_games: Set[str] = None
    ) -> List[Tuple[str, float]]:
        """
        基于用户画像的内容召回
        """
        exclude_games = exclude_games or set()
        candidates = []

        # 1. 偏好类目召回
        preferred_categories = user_profile.get("preferred_categories", {})
        for category, weight in sorted(preferred_categories.items(),
                                        key=lambda x: -x[1])[:3]:
            games = await self._get_games_by_category(category, limit=15)
            for game in games:
                if game["game_id"] not in exclude_games:
                    candidates.append((game["game_id"], weight * 0.4))

        # 2. 偏好提供商召回
        preferred_providers = user_profile.get("preferred_providers", {})
        for provider, weight in sorted(preferred_providers.items(),
                                        key=lambda x: -x[1])[:2]:
            games = await self._get_games_by_provider(provider, limit=10)
            for game in games:
                if game["game_id"] not in exclude_games:
                    candidates.append((game["game_id"], weight * 0.3))

        # 3. 风险偏好匹配（volatility）
        risk_preference = user_profile.get("risk_preference", "medium")
        games = await self._get_games_by_volatility(risk_preference, limit=10)
        for game in games:
            if game["game_id"] not in exclude_games:
                candidates.append((game["game_id"], 0.2))

        # 4. 主题偏好召回
        preferred_themes = user_profile.get("preferred_themes", [])
        for theme in preferred_themes[:3]:
            games = await self._get_games_by_theme(theme, limit=8)
            for game in games:
                if game["game_id"] not in exclude_games:
                    candidates.append((game["game_id"], 0.1))

        # 合并去重，按分数排序
        game_scores = defaultdict(float)
        for game_id, score in candidates:
            game_scores[game_id] += score

        ranked = sorted(game_scores.items(), key=lambda x: -x[1])
        return ranked[:top_k]
```

#### 3.1.6 热门召回（多维度）

```python
class GameHotRecall:
    """
    游戏热门召回：多维度热门榜单

    游戏场景特点：
    - 分时段热门（早/午/晚/深夜用户群体不同）
    - 分类目热门（Slots/Crash 各有热门榜）
    - 高 RTP 热门（部分用户偏好高返还率游戏）
    - 实时热门（过去1小时的投注热度）
    """

    def __init__(self, redis_client):
        self.redis = redis_client

    async def recall(
        self,
        context: dict,  # 包含 time_period, category 等
        top_k: int = 30,
        exclude_games: Set[str] = None
    ) -> List[Tuple[str, float]]:
        """
        多维度热门召回
        """
        exclude_games = exclude_games or set()
        candidates = []

        # 1. 实时热门（权重最高）
        realtime_hot = await self.redis.zrevrange(
            "game:hot:realtime", 0, 20, withscores=True
        )
        for game_id, score in realtime_hot:
            if game_id not in exclude_games:
                candidates.append((game_id, score * 0.4))

        # 2. 分时段热门
        time_period = context.get("time_period", "day")  # morning/afternoon/evening/night
        period_hot = await self.redis.zrevrange(
            f"game:hot:period:{time_period}", 0, 15, withscores=True
        )
        for game_id, score in period_hot:
            if game_id not in exclude_games:
                candidates.append((game_id, score * 0.3))

        # 3. 分类目热门（如果有类目上下文）
        category = context.get("category")
        if category:
            category_hot = await self.redis.zrevrange(
                f"game:hot:category:{category}", 0, 15, withscores=True
            )
            for game_id, score in category_hot:
                if game_id not in exclude_games:
                    candidates.append((game_id, score * 0.3))

        # 合并去重
        game_scores = defaultdict(float)
        for game_id, score in candidates:
            game_scores[game_id] += score

        # 归一化分数
        if game_scores:
            max_score = max(game_scores.values())
            game_scores = {k: v/max_score for k, v in game_scores.items()}

        ranked = sorted(game_scores.items(), key=lambda x: -x[1])
        return ranked[:top_k]
```

#### 3.1.7 新游戏召回

```python
class NewGameRecall:
    """
    新游戏召回：保证新游戏曝光

    使用 Thompson Sampling 平衡探索与利用
    """

    def __init__(self, redis_client, db_client):
        self.redis = redis_client
        self.db = db_client

    async def recall(
        self,
        user_profile: dict,
        top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """
        新游戏召回（上线7天内）
        """
        # 获取新游戏列表
        new_games = await self.db.get_new_games(days=7)

        if not new_games:
            return []

        # 使用 Thompson Sampling 选择
        candidates = []
        for game in new_games:
            # Beta 分布采样
            alpha = game.get("click_count", 1) + 1
            beta = game.get("impression_count", 1) - game.get("click_count", 0) + 1
            sampled_ctr = np.random.beta(alpha, beta)

            # 内容相似度加成
            content_bonus = self._compute_content_match(user_profile, game)

            score = sampled_ctr * 0.7 + content_bonus * 0.3
            candidates.append((game["game_id"], score))

        ranked = sorted(candidates, key=lambda x: -x[1])
        return ranked[:top_k]
```

#### 3.1.8 个性化召回（续玩 + 收藏）

```python
class PersonalRecall:
    """
    个性化召回：基于用户显式/隐式反馈

    - 续玩召回：最近玩过但未完成 Session 的游戏
    - 收藏召回：用户 Favorite 列表
    """

    async def recall(
        self,
        user_id: str,
        top_k: int = 15
    ) -> List[Tuple[str, float]]:
        candidates = []

        # 1. 续玩召回（最近3天玩过的游戏）
        recent_games = await self.redis.lrange(f"user:recent:{user_id}", 0, 10)
        for i, game_id in enumerate(recent_games):
            recency_score = 1.0 / (1 + i * 0.1)
            candidates.append((game_id, recency_score * 0.4))

        # 2. 收藏召回
        favorite_games = await self.db.get_user_favorites(user_id)
        for game in favorite_games[:5]:
            candidates.append((game["game_id"], 0.3))

        # 去重
        game_scores = {}
        for game_id, score in candidates:
            game_scores[game_id] = max(game_scores.get(game_id, 0), score)

        ranked = sorted(game_scores.items(), key=lambda x: -x[1])
        return ranked[:top_k]
```

#### 3.1.9 召回合并器

```python
class RecallMerger:
    """
    多路召回合并器

    参考 SparrowRecSys multipleRetrievalCandidates 的多路召回合并思想
    """

    def __init__(self):
        self.recall_sources = {}

    async def merge(
        self,
        user_id: str,
        user_type: str,
        context: dict,
        total_quota: int = 100
    ) -> List[dict]:
        """
        合并多路召回结果
        """
        # 获取配额
        quota = RECALL_QUOTA.get(user_type, RECALL_QUOTA["活跃用户"])

        all_candidates = {}
        recall_sources = {}

        # 并行执行各路召回
        tasks = [
            ("itemcf", self.itemcf_recall.recall(user_id, ...)),
            ("embedding", self.embedding_recall.recall(...)),
            ("content", self.content_recall.recall(...)),
            ("hot", self.hot_recall.recall(...)),
            ("new_game", self.new_game_recall.recall(...)),
            ("personal", self.personal_recall.recall(...)),
        ]

        results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

        for (source, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                continue

            source_quota = quota.get(source, 0)
            for game_id, score in result[:source_quota]:
                if game_id not in all_candidates:
                    all_candidates[game_id] = score
                    recall_sources[game_id] = source
                else:
                    # 多路命中的游戏，分数加成
                    all_candidates[game_id] = max(all_candidates[game_id], score) * 1.1

        # 按分数排序，截取 quota
        sorted_candidates = sorted(all_candidates.items(), key=lambda x: -x[1])

        return [
            {
                "game_id": game_id,
                "recall_score": score,
                "recall_source": recall_sources.get(game_id, "unknown")
            }
            for game_id, score in sorted_candidates[:total_quota]
        ]
```

#### 3.1.10 召回模块评估指标

| 指标类型 | 指标名称 | 说明 | 目标 |
|----------|----------|------|------|
| **覆盖率** | 召回覆盖率 | 被召回游戏占总游戏比例 | > 80% |
| **命中率** | Recall@K | 用户实际点击在召回集中的比例 | > 60% |
| **多样性** | 类目覆盖数 | 召回结果覆盖的类目数 | >= 3 |
| **新鲜度** | 新游戏召回率 | 新游戏在召回结果中的占比 | > 10% |
| **时效性** | 召回延迟 | 召回模块 P99 延迟 | < 20ms |

### 3.2 粗排模块（轻量双塔）

```python
class LightweightTwoTower:
    """
    轻量级粗排双塔
    - User Tower: 在线计算 (用户特征 → 64维向量)
    - Item Tower: 离线预计算存 Redis
    - 打分: 向量内积
    """
    def prerank(self, user_embedding, candidate_ids):
        # 批量获取候选物品 embedding
        item_embeddings = redis.mget([f"item:emb:{id}" for id in candidate_ids])
        # 内积计算相似度
        scores = np.dot(user_embedding, item_embeddings.T)
        return sorted(zip(candidate_ids, scores), key=lambda x: -x[1])[:30]
```

### 3.3 精排模块（DeepFM + 简化 DIN）

**特征设计：**

| 特征类型 | 特征列表 | 处理方式 |
|----------|----------|----------|
| 用户特征 | user_id, 注册天数, 用户等级, 偏好类目 | Embedding |
| 游戏特征 | game_id, category, provider, rtp, volatility | Embedding + 连续 |
| 交叉特征 | user×category历史CTR, user×provider偏好 | 在线计算 |
| 序列特征 | 最近5个游戏ID序列 | DIN Attention |
| 上下文 | 时段, 设备类型 | Embedding |

**模型选择：**

```python
# MVP阶段：DeepFM 为主
if user_behavior_count < 5:
    score = deepfm_model.predict(features)
else:
    # 有足够行为时，融合 DIN
    score = 0.4 * deepfm_score + 0.6 * din_score
```

### 3.4 重排模块

```python
class ReRanker:
    def rerank(self, ranked_list, rules):
        result = []
        for item in ranked_list:
            # 1. 多样性控制：同类目不连续超过2个
            if self._check_category_diversity(result, item):
                # 2. 强制插入：新游戏在位置 3, 8
                if len(result) in [2, 7] and self._has_new_game(ranked_list):
                    result.append(self._pop_new_game(ranked_list))
                result.append(item)
            if len(result) >= 10:
                break
        return result
```

### 3.5 冷启动策略（游戏场景专用）

游戏推荐系统面临两类冷启动问题：新用户、新游戏。以下是针对游戏场景的详细策略设计。

#### 3.5.1 新用户冷启动

**挑战：** 新用户无历史行为数据，无法使用协同过滤和 Embedding 召回。

**策略：利用 Side Information（边信息）**

```python
class NewUserColdStart:
    """
    新用户冷启动策略

    利用可获取的边信息进行初始推荐：
    1. 注册渠道（不同渠道用户偏好不同）
    2. 设备类型（iOS/Android/Web 用户行为差异）
    3. 注册时间（时段偏好）
    4. 地理位置（地区热门游戏差异）
    5. 首次访问页面（入口意图）
    """

    # 渠道-类目偏好映射（基于历史数据统计）
    CHANNEL_PREFERENCE = {
        "organic": {"slots": 0.4, "crash": 0.3, "live": 0.2, "virtual": 0.1},
        "facebook_ads": {"slots": 0.5, "crash": 0.2, "live": 0.2, "virtual": 0.1},
        "google_ads": {"slots": 0.3, "crash": 0.4, "live": 0.2, "virtual": 0.1},
        "affiliate": {"crash": 0.5, "slots": 0.3, "live": 0.1, "virtual": 0.1},
    }

    # 设备-风险偏好映射
    DEVICE_RISK_PREFERENCE = {
        "ios": "medium",      # iOS 用户偏保守
        "android": "high",    # Android 用户偏激进
        "web": "medium",
    }

    async def recommend(
        self,
        user_context: dict,
        top_k: int = 50
    ) -> List[dict]:
        """
        新用户推荐策略

        配额分配：60% 热门 + 20% 新游戏 + 20% 类目多样性
        """
        channel = user_context.get("channel", "organic")
        device = user_context.get("device", "web")
        time_period = user_context.get("time_period", "day")

        candidates = []

        # 1. 热门召回（60%）- 按渠道偏好加权
        channel_prefs = self.CHANNEL_PREFERENCE.get(channel, self.CHANNEL_PREFERENCE["organic"])
        hot_quota = int(top_k * 0.6)

        for category, weight in sorted(channel_prefs.items(), key=lambda x: -x[1]):
            category_quota = int(hot_quota * weight)
            hot_games = await self.hot_recall.recall(
                context={"category": category, "time_period": time_period},
                top_k=category_quota
            )
            for game_id, score in hot_games:
                candidates.append({
                    "game_id": game_id,
                    "score": score * weight,
                    "source": f"hot_{category}"
                })

        # 2. 新游戏召回（20%）- 增加探索
        new_quota = int(top_k * 0.2)
        new_games = await self.new_game_recall.recall(
            user_profile={"risk_preference": self.DEVICE_RISK_PREFERENCE.get(device, "medium")},
            top_k=new_quota
        )
        for game_id, score in new_games:
            candidates.append({
                "game_id": game_id,
                "score": score * 0.8,
                "source": "new_game"
            })

        # 3. 类目多样性（20%）- 确保覆盖所有类目
        diversity_quota = int(top_k * 0.2)
        existing_categories = set()
        for c in candidates:
            game_info = await self.game_service.get_game(c["game_id"])
            existing_categories.add(game_info.get("category"))

        for category in ["slots", "crash", "live", "virtual"]:
            if category not in existing_categories:
                category_games = await self.hot_recall.recall(
                    context={"category": category},
                    top_k=diversity_quota // 4
                )
                for game_id, score in category_games[:3]:
                    candidates.append({
                        "game_id": game_id,
                        "score": score * 0.5,
                        "source": f"diversity_{category}"
                    })

        # 去重排序
        seen = set()
        result = []
        for c in sorted(candidates, key=lambda x: -x["score"]):
            if c["game_id"] not in seen:
                seen.add(c["game_id"])
                result.append(c)

        return result[:top_k]
```

#### 3.5.2 新游戏冷启动

**挑战：** 新上线游戏无用户交互数据，无法计算协同过滤相似度和 Embedding。

**策略：Thompson Sampling + 内容相似度**

```python
class NewGameColdStart:
    """
    新游戏冷启动策略

    核心思想：
    1. 使用 Thompson Sampling 平衡探索与利用
    2. 利用游戏属性计算内容相似度，借用相似游戏的 Embedding
    3. 强制曝光池保证最低曝光量
    """

    def __init__(self, db_client, redis_client):
        self.db = db_client
        self.redis = redis_client
        self.min_impressions = 1000  # 最低曝光量

    async def get_new_game_score(
        self,
        game: dict,
        user_profile: dict
    ) -> float:
        """
        计算新游戏的推荐分数

        score = thompson_score * 0.5 + content_match * 0.3 + freshness * 0.2
        """
        # 1. Thompson Sampling 分数
        alpha = game.get("click_count", 0) + 1
        beta = game.get("impression_count", 0) - game.get("click_count", 0) + 1
        thompson_score = np.random.beta(alpha, beta)

        # 2. 内容匹配分数
        content_match = self._compute_content_match(user_profile, game)

        # 3. 新鲜度分数（越新分数越高）
        days_since_launch = (datetime.now() - game["launch_date"]).days
        freshness = max(0, 1 - days_since_launch / 7)  # 7天内线性衰减

        # 4. 强制曝光加成（未达到最低曝光量的游戏）
        if game.get("impression_count", 0) < self.min_impressions:
            boost = 1.5
        else:
            boost = 1.0

        score = (thompson_score * 0.5 + content_match * 0.3 + freshness * 0.2) * boost
        return score

    def _compute_content_match(self, user_profile: dict, game: dict) -> float:
        """
        计算用户画像与游戏属性的匹配度
        """
        score = 0.0

        # 类目匹配
        preferred_categories = user_profile.get("preferred_categories", {})
        if game["category"] in preferred_categories:
            score += preferred_categories[game["category"]] * 0.4

        # 提供商匹配
        preferred_providers = user_profile.get("preferred_providers", {})
        if game["provider"] in preferred_providers:
            score += preferred_providers[game["provider"]] * 0.3

        # 风险偏好匹配
        user_risk = user_profile.get("risk_preference", "medium")
        game_volatility = game.get("volatility", "medium")
        if user_risk == game_volatility:
            score += 0.2

        # 主题匹配
        preferred_themes = set(user_profile.get("preferred_themes", []))
        game_themes = set(game.get("themes", []))
        if preferred_themes & game_themes:
            score += 0.1

        return min(score, 1.0)

    async def borrow_embedding(self, new_game: dict) -> np.ndarray:
        """
        借用相似游戏的 Embedding（内容相似度加权平均）

        对于新游戏，找到属性最相似的 K 个已有游戏，
        加权平均它们的 Embedding 作为新游戏的初始 Embedding
        """
        # 找到同类目、同提供商的游戏
        similar_games = await self.db.find_similar_games(
            category=new_game["category"],
            provider=new_game["provider"],
            volatility=new_game.get("volatility"),
            limit=10
        )

        if not similar_games:
            return None

        embeddings = []
        weights = []

        for game in similar_games:
            emb = await self.redis.get(f"game:embedding:{game['game_id']}")
            if emb:
                embeddings.append(np.frombuffer(emb, dtype=np.float32))
                # 相似度作为权重
                sim = self._compute_game_similarity(new_game, game)
                weights.append(sim)

        if not embeddings:
            return None

        # 加权平均
        weights = np.array(weights) / sum(weights)
        borrowed_emb = np.average(embeddings, axis=0, weights=weights)

        return borrowed_emb
```

#### 3.5.3 冷启动策略总结

| 场景 | 策略 | 配额分配 | 关键技术 |
|------|------|----------|----------|
| **新用户** | Side Information + 热门 + 多样性 | 60%热门 + 20%新游戏 + 20%多样性 | 渠道偏好映射、设备风险偏好 |
| **新游戏** | Thompson Sampling + 内容相似 | 强制曝光池 + 动态配额 | Beta分布采样、Embedding借用 |

---

## 四、Python 技术栈选型

### 4.1 核心框架

| 组件 | 选型 | 版本 | 理由 |
|------|------|------|------|
| **Web 框架** | FastAPI | 0.100+ | 高性能、自动文档、类型检查 |
| **深度学习** | PyTorch | 2.0+ | 动态图、调试方便、社区活跃 |
| **数据处理** | Pandas + PySpark | - | 离线批处理 |
| **向量检索** | FAISS | - | 高效近邻搜索 |
| **任务队列** | Celery + Redis | - | 异步任务、定时更新 |
| **配置管理** | Pydantic | - | 类型安全配置 |

### 4.2 存储方案

| 存储 | 用途 | 说明 |
|------|------|------|
| **MySQL** | 业务数据 | 用户、游戏、行为日志 |
| **Redis** | 缓存+特征 | 实时特征、相似矩阵、推荐缓存 |
| **FAISS** | 向量索引 | 双塔模型召回 |
| **MinIO/S3** | 模型存储 | 训练模型、Embedding 文件 |

### 4.3 部署方案

```
┌─────────────────────────────────────────┐
│           Docker Compose 部署            │
├─────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌──────────┐  │
│  │FastAPI  │ │ Celery  │ │ Redis    │  │
│  │ (API)   │ │(Worker) │ │ (Cache)  │  │
│  └─────────┘ └─────────┘ └──────────┘  │
│  ┌─────────┐ ┌─────────┐               │
│  │  MySQL  │ │ Nginx   │               │
│  │  (DB)   │ │(Gateway)│               │
│  └─────────┘ └─────────┘               │
└─────────────────────────────────────────┘
```

---

## 五、数据模型设计

### 5.1 核心表结构

```sql
-- 用户画像表
CREATE TABLE user_profile (
    user_id VARCHAR(64) PRIMARY KEY,
    register_time TIMESTAMP,
    last_active_time TIMESTAMP,
    user_level INT,
    lifecycle_stage VARCHAR(20),  -- new/active
    preferred_categories JSONB,   -- {"Slots": 0.6, "Crash": 0.3}
    preferred_providers JSONB,
    total_play_count INT,
    total_bet_amount DECIMAL(15,2),
    updated_at TIMESTAMP
);

-- 游戏信息表  
CREATE TABLE game_info (
    game_id VARCHAR(64) PRIMARY KEY,
    game_name VARCHAR(128),
    category VARCHAR(32),         -- Slots/Crash/Live
    provider VARCHAR(64),         -- Pragmatic Play/Spribe
    rtp DECIMAL(5,2),
    volatility VARCHAR(20),       -- high/medium/low
    themes JSONB,                 -- ["mythology", "animal"]
    features JSONB,               -- ["megaways", "free_spins"]
    launch_date DATE,
    lifecycle_stage VARCHAR(20),  -- new/growth/mature
    is_featured BOOLEAN,
    thumbnail_url VARCHAR(256),
    play_count_7d INT,
    ctr_7d DECIMAL(5,4),
    updated_at TIMESTAMP
);

-- 用户行为表
CREATE TABLE user_behavior (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(64),
    game_id VARCHAR(64),
    behavior_type VARCHAR(20),    -- view/click/play/bet/favorite
    duration INT,
    bet_amount DECIMAL(15,2),
    created_at TIMESTAMP,
    INDEX idx_user_time (user_id, created_at),
    INDEX idx_game_time (game_id, created_at)
);
```

### 5.2 Redis 数据结构

```python
# 1. 游戏相似矩阵
# Key: game:sim:{game_id}
# Type: Hash
# Value: {similar_game_id: score, ...}

# 2. 用户行为序列
# Key: user:behavior:{user_id}
# Type: List (最近50条)
# Value: [game_id_1, game_id_2, ...]

# 3. 热门游戏榜
# Key: game:hot:{category}  或 game:hot:all
# Type: Sorted Set
# Score: play_count
# Member: game_id

# 4. 物品 Embedding
# Key: item:emb:{game_id}
# Type: String (64维 float32 bytes)

# 5. 推荐缓存
# Key: rec:cache:{user_id}:{scene}
# Type: String (JSON)
# TTL: 300s
```

---

## 六、API 接口设计

### 6.1 推荐接口

```
GET /api/v1/recommend/games

Query Parameters:
  - user_id: string (必填)
  - scene: string (必填) - home/slots/crash/similar
  - game_id: string (可选) - 相似推荐时使用
  - page_size: int (默认10)

Response:
{
    "code": 0,
    "data": {
        "games": [
            {
                "game_id": "gate_of_olympus",
                "game_name": "Gates of Olympus",
                "category": "Slots",
                "provider": "Pragmatic Play",
                "thumbnail_url": "https://...",
                "score": 0.95,
                "reason": "Based on your Slots preference"
            }
        ],
        "request_id": "xxx",
        "recall_source": ["hot", "item_cf"]
    }
}
```

### 6.2 管理接口

```
# 刷新热门榜单
POST /api/v1/admin/refresh/hot

# 更新游戏相似矩阵  
POST /api/v1/admin/refresh/similarity

# 健康检查
GET /api/v1/health
```

---

## 七、项目结构

```
game-recommendation-system/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── recommend.py    # 推荐接口
│   │   │   └── admin.py        # 管理接口
│   ├── core/
│   │   ├── __init__.py
│   │   ├── recall/
│   │   │   ├── hot_recall.py       # 热门召回
│   │   │   ├── itemcf_recall.py    # ItemCF召回
│   │   │   ├── content_recall.py   # 内容召回
│   │   │   └── merger.py           # 召回合并
│   │   ├── prerank/
│   │   │   └── two_tower.py        # 粗排双塔
│   │   ├── rank/
│   │   │   ├── deepfm.py           # DeepFM模型
│   │   │   ├── din.py              # DIN模型
│   │   │   └── ranker.py           # 精排服务
│   │   ├── rerank/
│   │   │   └── diversity.py        # 重排多样性
│   │   └── strategy/
│   │       ├── cold_start.py       # 冷启动
│   │       └── business_rules.py   # 业务规则
│   ├── data/
│   │   ├── __init__.py
│   │   ├── models.py           # 数据模型
│   │   ├── database.py         # 数据库连接
│   │   └── redis_client.py     # Redis客户端
│   └── utils/
│       ├── __init__.py
│       ├── feature_encoder.py  # 特征编码
│       └── logger.py           # 日志
├── offline/
│   ├── __init__.py
│   ├── feature_engineering.py  # 特征工程
│   ├── train_deepfm.py         # DeepFM训练
│   ├── train_din.py            # DIN训练
│   ├── compute_similarity.py   # 相似度计算
│   └── update_embeddings.py    # Embedding更新
├── tasks/
│   ├── __init__.py
│   ├── celery_app.py           # Celery配置
│   ├── scheduled_tasks.py      # 定时任务
│   └── realtime_tasks.py       # 实时任务
├── tests/
│   ├── test_recall.py
│   ├── test_rank.py
│   └── test_api.py
├── scripts/
│   ├── init_db.py              # 初始化数据库
│   ├── load_sample_data.py     # 加载样本数据
│   └── deploy.sh               # 部署脚本
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 八、开发计划

### 8.1 总体时间线

```
Phase 1: MVP版本 (Week 1-2)
├── Day 1-2: 基础架构搭建
├── Day 3-4: 召回模块实现
├── Day 5-6: 精排模块实现
├── Day 7-8: API服务与联调
├── Day 9:   冷启动与业务规则
└── Day 10:  测试与部署

Phase 2: 增强版本 (Week 3-4)
├── 双塔模型召回
├── 重排多样性优化
├── A/B测试框架
└── 监控告警

Phase 3: 高级特性 (Week 5-6)
├── DIN模型完善
├── 实时特征
├── 性能优化
└── 在线学习探索
```

### 8.2 Phase 1: MVP 详细计划

#### Day 1-2: 基础架构搭建

| 任务 | 具体内容 | 产出物 | 验收标准 |
|------|----------|--------|----------|
| 项目初始化 | 创建项目结构、配置管理 | 项目骨架代码 | 能启动空服务 |
| 数据库设计 | 创建表结构、Redis配置 | SQL脚本、连接池 | 数据库可连接 |
| 样本数据 | 构造模拟游戏/用户数据 | 100+游戏、1000+用户 | 数据可查询 |
| 基础框架 | FastAPI路由、中间件 | API骨架 | 健康检查接口可用 |

```bash
# Day 1 核心命令
mkdir -p game-recommendation-system/{app,offline,tasks,tests,scripts,docker}
pip install fastapi uvicorn sqlalchemy redis pydantic
```

#### Day 3-4: 召回模块实现

| 任务 | 具体内容 | 产出物 | 验收标准 |
|------|----------|--------|----------|
| 热门召回 | Redis ZSET存储、分类热门 | hot_recall.py | 能返回热门列表 |
| Item-CF召回 | 离线计算相似矩阵 | itemcf_recall.py | 相似矩阵存入Redis |
| 内容召回 | 基于用户偏好匹配 | content_recall.py | 能按标签匹配 |
| 召回合并 | 多路召回去重、配额 | merger.py | 合并后~50候选 |

#### Day 5-6: 精排模块实现

| 任务 | 具体内容 | 产出物 | 验收标准 |
|------|----------|--------|----------|
| 特征工程 | 用户/游戏/交叉特征 | feature_encoder.py | 特征向量正确 |
| DeepFM模型 | PyTorch实现、训练脚本 | deepfm.py | AUC > 0.70 |
| 精排服务 | 模型加载、批量推理 | ranker.py | 能返回排序结果 |
| 简单重排 | 多样性规则 | diversity.py | 无连续同类目 |

#### Day 7-8: API服务与联调

| 任务 | 具体内容 | 产出物 | 验收标准 |
|------|----------|--------|----------|
| 推荐接口 | 完整推荐链路 | recommend.py | 端到端可用 |
| 链路测试 | 端到端测试 | test_api.py | 全链路通过 |
| 性能优化 | 缓存、批处理 | - | P99 < 100ms |

#### Day 9: 冷启动与业务规则

| 任务 | 具体内容 | 产出物 | 验收标准 |
|------|----------|--------|----------|
| 新用户冷启动 | 热门+多样性策略 | cold_start.py | 新用户有推荐 |
| 新游戏曝光 | 强制曝光池 | business_rules.py | 新游戏有曝光 |
| 业务规则 | 类目打散等 | - | 规则生效 |

#### Day 10: 测试与部署

| 任务 | 具体内容 | 产出物 | 验收标准 |
|------|----------|--------|----------|
| 单元测试 | 各模块测试 | tests/ | 覆盖率>80% |
| Docker化 | Dockerfile、Compose | docker/ | 容器启动正常 |
| 部署文档 | 部署、运维文档 | README.md | 可按文档部署 |
| 上线验证 | 生产环境验证 | - | 服务稳定运行 |

### 8.3 Phase 2: 增强版本 (Week 3-4)

| 周次 | 任务 | 说明 |
|------|------|------|
| Week 3 | 双塔模型召回 | 训练用户/物品塔，FAISS索引 |
| Week 3 | 粗排模块 | 轻量双塔粗排服务 |
| Week 4 | A/B测试框架 | 分流、指标收集 |
| Week 4 | 监控告警 | Prometheus + Grafana |

### 8.4 Phase 3: 高级特性 (Week 5-6)

| 周次 | 任务 | 说明 |
|------|------|------|
| Week 5 | DIN完善 | Attention机制、行为序列 |
| Week 5 | 实时特征 | Session特征、Redis存储 |
| Week 6 | 性能优化 | 缓存策略、模型推理优化 |
| Week 6 | 在线学习 | 增量模型更新探索 |

---

## 九、关键指标

### 9.1 MVP 验收指标

| 指标类型 | 指标 | 目标 |
|----------|------|------|
| **离线** | DeepFM AUC | > 0.70 |
| **在线** | 推荐API P99延迟 | < 100ms |
| **在线** | 推荐API QPS | > 100 |
| **业务** | 推荐覆盖率 | > 80% 游戏被推荐 |
| **可用性** | 服务成功率 | > 99.5% |

### 9.2 长期业务指标

| 指标 | 说明 | 目标 |
|------|------|------|
| 推荐CTR | 推荐位点击率 | > 15% |
| 推荐CVR | 推荐后开始游戏率 | > 40% |
| 新游戏曝光率 | 新游戏推荐占比 | > 10% |
| 新用户转化 | 新用户首日游戏率 | > 50% |

---

## 十、风险与应对

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|----------|
| 模型训练数据不足 | 中 | 高 | 使用规则兜底、冷启动策略 |
| 推荐延迟过高 | 中 | 高 | 预计算、缓存、降级热门 |
| 用户画像不准确 | 中 | 中 | 实时行为更新、探索策略 |
| 推荐多样性差 | 低 | 中 | 重排多样性、类目打散 |

---

## 十一、总结

本方案基于 SparrowRecSys 架构思想，采用 Python 统一技术栈，设计了一个**快速可落地**的游戏推荐系统：

1. **分层架构**：召回→粗排→精排→重排，各层独立可迭代
2. **技术简化**：相比原文档减少 Kafka/Flink 等复杂组件
3. **MVP 优先**：10天完成核心功能，后续渐进增强
4. **Python 全栈**：FastAPI + PyTorch + PySpark，降低维护成本

建议按 Phase 1 计划启动开发，在 2 周内交付 MVP 版本，验证核心推荐链路效果后再迭代优化。

---

## 后续建议

我已经为您完成了详细的技术方案和开发计划。接下来您可以考虑：

1. **确认技术选型**：您对 FastAPI + PyTorch + MySQL + Redis 的技术栈是否满意？
2. **开始 MVP 开发**：如果方案符合预期，我可以帮您开始创建项目骨架代码
3. **调整简化程度**：如果某些简化不符合需求（如需要 Kafka 实时流处理），可以调整方案
4. **生成详细的设计文档**：如果需要，我可以将此方案保存为 Markdown 文档到项目中
