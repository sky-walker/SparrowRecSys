
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
│  │  Redis   │PostgreSQL│  FAISS   │       特征存储 (Redis)        │ │
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
| MySQL+HBase | PostgreSQL + Redis | 单一数据库简化运维 |
| 复杂的 DIEN/MMOE | DeepFM + 简化版 DIN | MVP 阶段足够 |

---

## 三、核心模块设计

### 3.1 召回模块（4路召回）

```python
# 召回策略设计
召回配额分配 = {
    "新用户": {"热门": 25, "内容": 15, "新游戏": 10, "Item-CF": 0},
    "活跃用户": {"热门": 10, "内容": 10, "新游戏": 5, "Item-CF": 25},
    "流失回归": {"热门": 15, "内容": 10, "新游戏": 5, "Item-CF": 20}
}
```

| 召回路 | 实现方式 | 配额 | 说明 |
|--------|----------|------|------|
| **热门召回** | Redis ZSET | 10-25 | 分时段/分类热门 |
| **Item-CF** | 预计算相似矩阵 | 0-25 | 基于用户历史 |
| **内容召回** | 属性匹配 | 10-15 | 基于用户偏好标签 |
| **新游戏召回** | 强制池 | 5-10 | 7天内新游戏 |

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

### 3.5 冷启动策略

| 场景 | 策略 |
|------|------|
| **新用户** | 60%热门 + 20%新游戏 + 20%类目多样性 |
| **新游戏** | 强制曝光池 + Thompson Sampling |
| **流失回归** | 40%历史偏好 + 30%新游戏 + 30%热门 |

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
| **PostgreSQL** | 业务数据 | 用户、游戏、行为日志 |
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
│  │PostgreSQL│ │ Nginx  │               │
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
    lifecycle_stage VARCHAR(20),  -- new/active/churn
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

### 6.2 行为上报接口

```
POST /api/v1/behavior/track

Request Body:
{
    "user_id": "user_001",
    "game_id": "aviator",
    "behavior_type": "play",
    "duration": 300,
    "bet_amount": 100.00
}

Response:
{
    "code": 0,
    "message": "success"
}
```

### 6.3 管理接口

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
│   │   │   ├── behavior.py     # 行为上报
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
| 行为上报 | 行为记录、序列更新 | behavior.py | 行为入库 |
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

1. **确认技术选型**：您对 FastAPI + PyTorch + PostgreSQL + Redis 的技术栈是否满意？
2. **开始 MVP 开发**：如果方案符合预期，我可以帮您开始创建项目骨架代码
3. **调整简化程度**：如果某些简化不符合需求（如需要 Kafka 实时流处理），可以调整方案
4. **生成详细的设计文档**：如果需要，我可以将此方案保存为 Markdown 文档到项目中
