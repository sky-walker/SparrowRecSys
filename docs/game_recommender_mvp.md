# 🎮 游戏推荐系统 MVP 版技术方案

> 基于 SparrowRecSys 架构思想精简优化，目标：**1-2 周快速上线**

---

## 一、设计原则

| 原则 | 说明 |
|------|------|
| **MVP 优先** | 先跑通核心链路，后续迭代增强 |
| **技术简化** | FastAPI + MySQL + Redis，无 Kafka/Flink |
| **Python 统一** | 全栈 Python，降低维护成本 |
| **分层解耦** | 召回/排序/服务独立，支持独立迭代 |

---

## 二、系统架构

### 2.1 MVP 简化架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户请求层                               │
│        Web/App  →  FastAPI  →  推荐服务                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   推荐服务层 (FastAPI)                        │
│   ┌──────────┬──────────┬──────────┬──────────────────────┐ │
│   │ 召回模块  │ 排序模块  │ 重排模块  │  冷启动策略          │ │
│   │ ~50候选  │ DeepFM   │ 规则打散  │                      │ │
│   └──────────┴──────────┴──────────┴──────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      数据存储层                               │
│   ┌──────────────────┬──────────────────────────────────┐   │
│   │  MySQL (业务数据)  │  Redis (缓存+热门榜+相似矩阵)    │   │
│   └──────────────────┴──────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   离线计算层 (定时任务)                        │
│   ┌────────────────┬────────────────┬─────────────────────┐ │
│   │ 热门榜单更新     │ 相似度矩阵计算  │ DeepFM 模型训练     │ │
│   │ (每小时)        │ (每日)         │ (每周)              │ │
│   └────────────────┴────────────────┴─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 与原设计的简化对比

| 原设计 | MVP 简化 | 理由 |
|--------|----------|------|
| 6 路召回 | **3 路召回** (热门+Item-CF+内容) | 足够覆盖主要场景 |
| Kafka + Flink 实时特征 | **Redis + 定时任务** | 降低运维复杂度 |
| 复杂分区表 + 多维统计表 | **核心表 + 简单索引** | MVP 数据量小 |
| A/B 测试 + 复杂重排 | **简单规则重排** | 后续版本添加 |
| 粗排双塔 + 精排 DeepFM + DIN | **仅 DeepFM** | 简化模型层 |

---

## 三、精简数据库设计

### 3.1 核心表结构 (仅 4 张表)

#### 3.1.1 用户表 (users)

```sql
CREATE TABLE users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL COMMENT '用户唯一标识',
    username VARCHAR(128) DEFAULT NULL,
    register_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    register_channel VARCHAR(64) DEFAULT NULL COMMENT '注册渠道',
    register_device VARCHAR(32) DEFAULT NULL COMMENT '设备类型: ios/android/web',
    last_active_time DATETIME DEFAULT NULL,
    status TINYINT UNSIGNED DEFAULT 1 COMMENT '1-正常 2-VIP',
    
    -- 用户画像字段 (MVP 简化：合并到用户表)
    preferred_categories JSON DEFAULT NULL COMMENT '类目偏好: {"slots": 0.5, "crash": 0.3}',
    preferred_providers JSON DEFAULT NULL COMMENT '提供商偏好',
    behavior_count INT UNSIGNED DEFAULT 0 COMMENT '总行为数',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_user_id (user_id),
    KEY idx_last_active (last_active_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';
```

#### 3.1.2 游戏表 (games)

```sql
CREATE TABLE games (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    game_id VARCHAR(64) NOT NULL COMMENT '游戏唯一标识',
    game_name VARCHAR(128) NOT NULL,
    category VARCHAR(32) NOT NULL COMMENT '类目: slots/crash/live/virtual',
    provider VARCHAR(64) NOT NULL COMMENT '提供商',
    
    -- 游戏属性
    rtp DECIMAL(5,2) DEFAULT NULL COMMENT '返还率',
    volatility VARCHAR(20) DEFAULT 'medium' COMMENT 'low/medium/high',
    themes JSON DEFAULT NULL COMMENT '主题标签',
    thumbnail_url VARCHAR(512) DEFAULT NULL,
    
    -- 状态
    status TINYINT UNSIGNED DEFAULT 1 COMMENT '1-上线 0-下线',
    is_new TINYINT(1) DEFAULT 0 COMMENT '是否新游戏',
    launch_date DATE DEFAULT NULL,
    
    -- 热度统计 (定时任务更新)
    play_count_24h INT UNSIGNED DEFAULT 0,
    play_count_7d INT UNSIGNED DEFAULT 0,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_game_id (game_id),
    KEY idx_category_status (category, status),
    KEY idx_hot_7d (status, play_count_7d DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='游戏表';
```

#### 3.1.3 用户行为表 (user_behaviors)

```sql
CREATE TABLE user_behaviors (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    game_id VARCHAR(64) NOT NULL,
    behavior_type VARCHAR(20) NOT NULL COMMENT 'click/play/favorite',
    duration INT UNSIGNED DEFAULT 0 COMMENT '游戏时长(秒)',
    behavior_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY idx_user_time (user_id, behavior_time),
    KEY idx_game_time (game_id, behavior_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户行为表';
```

#### 3.1.4 游戏相似度表 (game_similarities)

```sql
CREATE TABLE game_similarities (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    game_id VARCHAR(64) NOT NULL,
    similar_game_id VARCHAR(64) NOT NULL,
    similarity_score DECIMAL(6,5) NOT NULL COMMENT '相似度 0-1',
    rank_position SMALLINT UNSIGNED DEFAULT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_game_pair (game_id, similar_game_id),
    KEY idx_game_rank (game_id, rank_position)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='游戏相似度表';
```

### 3.2 Redis 数据结构 (精简版)

| Key Pattern | 类型 | TTL | 用途 |
|-------------|------|-----|------|
| `game:hot:all` | Sorted Set | 1小时 | 全站热门榜 |
| `game:hot:{category}` | Sorted Set | 1小时 | 分类热门榜 |
| `game:similar:{game_id}` | Hash | 1天 | 游戏相似矩阵 |
| `user:recent:{user_id}` | List | 7天 | 用户最近游戏 |
| `rec:cache:{user_id}` | String | 5分钟 | 推荐缓存 |

---

## 四、精简召回算法 (3 路召回)

### 4.1 召回架构

```
          ┌─────────────────┐
          │    用户请求      │
          └────────┬────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
    ▼              ▼              ▼
┌────────┐   ┌────────┐   ┌────────────┐
│热门召回 │   │Item-CF │   │  内容召回   │
│ 20个   │   │  20个  │   │   10个     │
└───┬────┘   └───┬────┘   └─────┬──────┘
    │            │              │
    └────────────┴──────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │  合并去重 ~50个  │
          └────────┬────────┘
                   │
                   ▼
          ┌─────────────────┐
          │  DeepFM 排序    │
          └────────┬────────┘
                   │
                   ▼
          ┌─────────────────┐
          │  规则重排 ~10个  │
          └─────────────────┘
```

### 4.2 热门召回

```python
class HotRecall:
    """热门召回：从 Redis Sorted Set 获取热门游戏"""

    async def recall(self, category: str = None, top_k: int = 20) -> List[dict]:
        key = f"game:hot:{category}" if category else "game:hot:all"
        hot_games = await redis.zrevrange(key, 0, top_k - 1, withscores=True)
        return [{"game_id": g, "score": s, "source": "hot"} for g, s in hot_games]
```

### 4.3 Item-CF 召回

```python
class ItemCFRecall:
    """
    协同过滤召回
    参考 SparrowRecSys Embedding.scala 的设计思想
    """

    async def recall(self, user_id: str, top_k: int = 20) -> List[dict]:
        # 获取用户最近玩过的游戏
        recent_games = await redis.lrange(f"user:recent:{user_id}", 0, 9)
        if not recent_games:
            return []

        candidates = {}
        for game_id in recent_games:
            similar = await redis.hgetall(f"game:similar:{game_id}")
            for sim_game, score in similar.items():
                if sim_game not in set(recent_games):
                    candidates[sim_game] = max(candidates.get(sim_game, 0), float(score))

        sorted_items = sorted(candidates.items(), key=lambda x: -x[1])[:top_k]
        return [{"game_id": g, "score": s, "source": "itemcf"} for g, s in sorted_items]
```

### 4.4 内容召回

```python
class ContentRecall:
    """内容召回：基于用户偏好匹配游戏属性"""

    async def recall(self, user_profile: dict, top_k: int = 10) -> List[dict]:
        preferred_category = max(
            user_profile.get("preferred_categories", {"slots": 1}).items(),
            key=lambda x: x[1]
        )[0]

        # 从偏好类目中召回热门游戏
        games = await self.db.query("""
            SELECT game_id, play_count_7d
            FROM games
            WHERE category = %s AND status = 1
            ORDER BY play_count_7d DESC LIMIT %s
        """, (preferred_category, top_k))

        return [{"game_id": g["game_id"], "score": 0.5, "source": "content"} for g in games]
```

### 4.5 召回合并器

```python
class RecallMerger:
    """多路召回合并"""

    async def merge(self, user_id: str, user_profile: dict, category: str = None) -> List[dict]:
        # 并行执行三路召回
        hot_task = self.hot_recall.recall(category, top_k=20)
        cf_task = self.itemcf_recall.recall(user_id, top_k=20)
        content_task = self.content_recall.recall(user_profile, top_k=10)

        results = await asyncio.gather(hot_task, cf_task, content_task)

        # 合并去重
        seen = set()
        candidates = []
        for result in results:
            for item in result:
                if item["game_id"] not in seen:
                    seen.add(item["game_id"])
                    candidates.append(item)

        return candidates[:50]
```

---

## 五、排序模型 (DeepFM)

### 5.1 特征设计 (精简版)

| 特征类型 | 特征 | 处理方式 |
|----------|------|----------|
| 用户特征 | user_id, 注册天数, 行为数 | Embedding + 数值 |
| 游戏特征 | game_id, category, provider, rtp | Embedding + 数值 |
| 交叉特征 | user×category偏好度 | 在线计算 |
| 上下文 | 时段, 设备类型 | Embedding |

### 5.2 DeepFM 模型结构

```python
class DeepFM(nn.Module):
    """
    MVP 精排模型
    参考 SparrowRecSys TFRecModel 的设计
    """
    def __init__(self, feature_dims, embed_dim=8, hidden_dims=[64, 32]):
        super().__init__()
        self.embeddings = nn.ModuleList([
            nn.Embedding(dim, embed_dim) for dim in feature_dims
        ])
        # FM 交叉
        self.fm_first = nn.Linear(sum(feature_dims), 1)
        # DNN
        input_dim = len(feature_dims) * embed_dim
        layers = []
        for h_dim in hidden_dims:
            layers.extend([nn.Linear(input_dim, h_dim), nn.ReLU(), nn.Dropout(0.2)])
            input_dim = h_dim
        layers.append(nn.Linear(input_dim, 1))
        self.dnn = nn.Sequential(*layers)

    def forward(self, x):
        # Embedding
        embeds = [self.embeddings[i](x[:, i]) for i in range(x.shape[1])]
        embed_concat = torch.cat(embeds, dim=1)
        # FM 二阶交叉
        sum_of_square = sum([e ** 2 for e in embeds])
        square_of_sum = sum(embeds) ** 2
        fm_cross = 0.5 * (square_of_sum - sum_of_square).sum(dim=1, keepdim=True)
        # DNN
        dnn_out = self.dnn(embed_concat)
        # 输出
        return torch.sigmoid(fm_cross + dnn_out)
```

### 5.3 简单重排规则

```python
def rerank(ranked_list: List[dict], max_same_category: int = 2) -> List[dict]:
    """
    重排规则：
    1. 同类目不连续超过2个
    2. 新游戏强制插入位置 3
    """
    result = []
    category_streak = {}
    new_games = [g for g in ranked_list if g.get("is_new")]

    for game in ranked_list:
        cat = game.get("category")
        if category_streak.get(cat, 0) >= max_same_category:
            continue
        result.append(game)
        category_streak[cat] = category_streak.get(cat, 0) + 1

        # 重置其他类目计数
        for k in category_streak:
            if k != cat:
                category_streak[k] = 0

        # 位置3插入新游戏
        if len(result) == 3 and new_games:
            result.append(new_games.pop(0))

        if len(result) >= 10:
            break

    return result
```

---

## 六、冷启动策略

### 6.1 新用户冷启动

```python
async def cold_start_for_new_user(user_context: dict) -> List[dict]:
    """
    新用户策略：70% 热门 + 30% 多样性
    利用注册渠道和设备信息
    """
    channel = user_context.get("channel", "organic")

    # 渠道偏好映射
    CHANNEL_PREF = {
        "organic": "slots",
        "facebook_ads": "slots",
        "google_ads": "crash",
        "affiliate": "crash"
    }

    preferred_cat = CHANNEL_PREF.get(channel, "slots")

    # 70% 偏好类目热门
    hot_games = await hot_recall.recall(preferred_cat, top_k=7)

    # 30% 其他类目多样性
    other_cats = ["slots", "crash", "live", "virtual"]
    other_cats.remove(preferred_cat) if preferred_cat in other_cats else None
    diversity_games = []
    for cat in other_cats:
        games = await hot_recall.recall(cat, top_k=1)
        diversity_games.extend(games)

    return hot_games + diversity_games
```

### 6.2 新游戏冷启动

- 新游戏（上线7天内）强制进入热门榜 Top20
- 在推荐结果位置 3 强制插入新游戏
- 累计曝光 1000 次后，按真实 CTR 排序

---

## 七、技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 高性能异步 |
| 数据库 | MySQL 8.0 | 业务数据存储 |
| 缓存 | Redis 7.0 | 热门榜/相似矩阵/缓存 |
| 深度学习 | PyTorch 2.0 | DeepFM 模型 |
| 任务调度 | APScheduler | 定时任务 |
| 部署 | Docker Compose | 简化运维 |

---

## 八、项目结构

```
game-rec-mvp/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置
│   ├── api/
│   │   └── recommend.py     # 推荐接口
│   ├── core/
│   │   ├── recall/
│   │   │   ├── hot.py       # 热门召回
│   │   │   ├── itemcf.py    # Item-CF 召回
│   │   │   ├── content.py   # 内容召回
│   │   │   └── merger.py    # 召回合并
│   │   ├── rank/
│   │   │   ├── deepfm.py    # DeepFM 模型
│   │   │   └── ranker.py    # 排序服务
│   │   └── rerank.py        # 重排规则
│   └── data/
│       ├── database.py      # MySQL 连接
│       └── redis_client.py  # Redis 连接
├── offline/
│   ├── compute_similarity.py  # 计算相似度矩阵
│   ├── update_hot.py          # 更新热门榜
│   └── train_deepfm.py        # 训练 DeepFM
├── scripts/
│   ├── init_db.sql          # 初始化数据库
│   └── sample_data.py       # 样本数据
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 九、开发计划 (1-2 周)

### 9.1 第一周：核心功能

| 天数 | 任务 | 产出物 | 验收标准 |
|------|------|--------|----------|
| **Day 1** | 项目初始化 + 数据库设计 | 表结构、项目骨架 | 数据库可连接 |
| **Day 2** | 样本数据 + Redis 结构 | 100+游戏数据 | 热门榜可查询 |
| **Day 3** | 热门召回 + Item-CF 召回 | recall 模块 | 召回结果正确 |
| **Day 4** | 内容召回 + 召回合并 | merger 模块 | 多路合并正常 |
| **Day 5** | DeepFM 模型实现 | rank 模块 | 模型可推理 |
| **Day 6** | 推荐 API 完整链路 | /recommend 接口 | 端到端可用 |
| **Day 7** | 冷启动 + 重排规则 | 策略模块 | 新用户有推荐 |

### 9.2 第二周：完善部署

| 天数 | 任务 | 产出物 | 验收标准 |
|------|------|--------|----------|
| **Day 8** | 离线任务 (热门榜/相似度) | offline 脚本 | 定时任务运行 |
| **Day 9** | 单元测试 + 集成测试 | tests/ | 覆盖率 >70% |
| **Day 10** | Docker 化 + 部署文档 | docker-compose.yml | 容器启动正常 |

### 9.3 核心功能清单

#### ✅ MVP 版本必须包含

| 功能 | 说明 |
|------|------|
| 首页推荐 | 个性化推荐 10 款游戏 |
| 分类推荐 | 按类目(slots/crash/live)推荐 |
| 热门召回 | 实时热门 + 分类热门 |
| Item-CF 召回 | 基于用户历史的协同过滤 |
| DeepFM 排序 | 点击率预估排序 |
| 新用户冷启动 | 基于渠道/设备的推荐 |
| 新游戏曝光 | 强制位置插入 |

#### ⏳ 后续版本添加 (MVP+1)

| 功能 | 说明 | 优先级 |
|------|------|--------|
| Embedding 召回 | 双塔模型向量召回 | P1 |
| DIN 模型 | 行为序列注意力 | P1 |
| A/B 测试框架 | 分流和效果对比 | P2 |
| 实时特征 | 用户 Session 特征 | P2 |
| 监控告警 | Prometheus + Grafana | P2 |
| 粗排模块 | 轻量双塔粗排 | P3 |

---

## 十、验收指标

### 10.1 MVP 验收

| 指标 | 目标 |
|------|------|
| 推荐 API P99 延迟 | < 100ms |
| 推荐 API QPS | > 50 |
| 服务可用性 | > 99% |
| DeepFM AUC | > 0.68 |

### 10.2 业务指标 (上线后观察)

| 指标 | 目标 |
|------|------|
| 推荐位 CTR | > 10% |
| 新用户首日游戏率 | > 40% |
| 新游戏曝光率 | > 5% |

---

## 十一、总结

本 MVP 方案相比原设计做了以下核心简化：

| 维度 | 原设计 | MVP |
|------|--------|-----|
| **数据库** | 11 张表 + 复杂分区 | 4 张核心表 |
| **召回** | 6 路召回 | 3 路召回 |
| **排序** | 粗排 + 精排(DeepFM+DIN) | 仅 DeepFM |
| **重排** | A/B 测试 + 多规则 | 简单规则 |
| **技术栈** | Kafka + Flink + 多语言 | Python 全栈 |
| **开发周期** | 6 周 | 1-2 周 |

**核心理念**：先用最小可行产品验证推荐效果，再根据业务反馈逐步迭代增强。

---

*文档版本: v1.0 MVP*
*创建日期: 2026-01-18*
*参考来源: SparrowRecSys 项目架构*

