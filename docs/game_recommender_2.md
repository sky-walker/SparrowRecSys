我需要先阅读您提供的文档和了解 SparrowRecSys 项目的架构结构，然后为您制定详细的技术方案。

[3 tools called]

让我进一步了解 SparrowRecSys 项目的代码架构。

[3 tools called]

让我再查看一些核心代码来了解实现细节。

[3 tools called]

根据我对两份设计文档和 SparrowRecSys 项目架构的深入分析，我为您制定以下完整的技术方案和开发计划。

---

# 🎮 游戏推荐系统技术方案与开发计划

## 一、项目概述与架构设计

### 1.1 SparrowRecSys 架构优势分析

通过分析 SparrowRecSys 项目，我总结出以下可借鉴的架构优势：

| 优势 | SparrowRecSys 实现 | 游戏推荐系统改进方向 |
|------|-------------------|-------------------|
| **模块化设计** | 离线训练(Spark/TF) + 在线服务(Jetty) 分离 | 全 Python 统一技术栈，降低维护成本 |
| **多模型支持** | DeepFM、DIN、Wide&Deep、NeuralCF | 保留核心模型，简化为 DeepFM + 双塔 |
| **Embedding 存储** | Redis 存储用户/物品 Embedding | 沿用方案，增加实时特征支持 |
| **TF Serving** | 模型服务独立部署 | 简化为 FastAPI 内嵌推理，MVP 阶段更轻量 |

### 1.2 简化版系统架构（Python 全栈）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户请求层                                      │
│     Web/App → Nginx(负载均衡) → FastAPI Gateway                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      推荐服务层 (FastAPI + Python)                        │
│  ┌───────────┬───────────┬───────────┬───────────┬─────────────────┐   │
│  │  召回模块   │  粗排模块   │  精排模块   │  重排模块   │    缓存模块      │   │
│  │(Recall)   │(PreRank)  │ (Ranking) │ (ReRank)  │   (Cache)       │   │
│  │ ~300候选   │  ~100候选  │   ~30候选  │  ~15结果   │                 │   │
│  └───────────┴───────────┴───────────┴───────────┴─────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          数据存储层                                       │
│  ┌───────────┬───────────┬───────────┬─────────────────────────────┐   │
│  │   Redis    │  MySQL    │   FAISS   │      Elasticsearch         │   │
│  │ (特征缓存)  │ (业务数据) │ (向量索引) │      (游戏检索,可选)        │   │
│  └───────────┴───────────┴───────────┴─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      离线训练层 (Python)                                  │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  PyTorch模型训练 → 特征工程 → 样本构建 → 定时任务(APScheduler)       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 核心模块设计（简化版）

#### 召回层设计（四路召回）

| 召回策略 | MVP 实现方式 | 配额 | 延迟目标 |
|---------|------------|------|---------|
| **Item-CF** | 预计算相似度矩阵，Redis 存储 | 100 | <5ms |
| **热门召回** | 多维度热门榜单(全站/分类) | 80 | <3ms |
| **内容召回** | 属性匹配(category/provider) | 60 | <5ms |
| **新游戏召回** | 强制曝光池 | 20 | <2ms |

#### 精排层设计（简化版）

```
MVP 阶段：DeepFM 单模型
        │
        ▼
┌─────────────────────────────────────────────┐
│              DeepFM 模型                     │
│  ┌─────────────────────────────────────┐   │
│  │  特征输入                             │   │
│  │  ├── 用户特征: user_id, level, 偏好  │   │
│  │  ├── 游戏特征: game_id, category,   │   │
│  │  │            provider, rtp, vol    │   │
│  │  ├── 交叉特征: user_category偏好度   │   │
│  │  └── 上下文: 时间段, 设备类型        │   │
│  └─────────────────────────────────────┘   │
│                    │                        │
│         ┌─────────┼─────────┐              │
│         ▼         ▼         ▼              │
│    ┌────────┐┌────────┐┌────────┐         │
│    │ 一阶项  ││ FM二阶  ││  DNN   │         │
│    └────┬───┘└────┬───┘└────┬───┘         │
│         └─────────┼─────────┘              │
│                   ▼                        │
│           Sigmoid → pCTR                   │
└─────────────────────────────────────────────┘
```

---

## 二、技术栈选型

### 2.1 Python 技术栈

| 层级 | 组件 | 选型 | 版本 | 理由 |
|------|-----|------|-----|------|
| **Web框架** | API 服务 | FastAPI | 0.100+ | 高性能、自动文档、类型检查 |
| **数据库** | ORM | SQLAlchemy | 2.0+ | 异步支持、成熟稳定 |
| | 连接池 | asyncpg | 0.28+ | PostgreSQL 异步驱动 |
| **缓存** | Redis 客户端 | redis-py | 5.0+ | 异步支持、功能完整 |
| **深度学习** | 模型训练 | PyTorch | 2.0+ | 动态图、torch.compile 加速 |
| | 模型推理 | ONNX Runtime | 1.16+ | 高性能推理、跨平台 |
| **向量检索** | 索引 | FAISS | 1.7+ | Facebook 开源、性能优异 |
| **数据处理** | DataFrame | Pandas | 2.0+ | 数据处理标准库 |
| | 特征工程 | NumPy | 1.24+ | 数值计算基础 |
| **任务调度** | 定时任务 | APScheduler | 3.10+ | 轻量、易用 |
| | 异步任务 | Celery | 5.3+ | 分布式任务队列 |
| **监控** | 指标采集 | prometheus-client | 0.18+ | 标准监控方案 |
| **测试** | 单元测试 | pytest | 7.4+ | Python 标准测试框架 |

### 2.2 数据存储方案

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据存储架构                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  MySQL/PostgreSQL (业务数据)                                    │
│  ├── user_profile: 用户画像                                     │
│  ├── game_info: 游戏信息                                        │
│  ├── user_behavior: 用户行为日志                                │
│  └── recommendation_log: 推荐日志(评估用)                       │
│                                                                 │
│  Redis (缓存 + 实时特征)                                        │
│  ├── game:sim:{game_id} → Hash: 相似游戏及分数                 │
│  ├── user:emb:{user_id} → String: 用户Embedding                │
│  ├── game:emb:{game_id} → String: 游戏Embedding                │
│  ├── hot:global → ZSet: 全站热门榜                             │
│  ├── hot:category:{cat} → ZSet: 分类热门榜                     │
│  ├── user:session:{user_id} → Hash: Session实时特征            │
│  └── rec:cache:{user_id}:{scene} → List: 推荐结果缓存          │
│                                                                 │
│  FAISS (向量索引, 文件存储)                                     │
│  └── game_index.faiss: 游戏Embedding索引                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 项目目录结构

```
game-recommendation-system/
├── app/                          # 主应用
│   ├── __init__.py
│   ├── main.py                   # FastAPI 入口
│   ├── config.py                 # 配置管理
│   ├── api/                      # API 路由
│   │   ├── __init__.py
│   │   ├── recommend.py          # 推荐接口
│   │   ├── behavior.py           # 行为上报
│   │   └── admin.py              # 管理接口
│   ├── core/                     # 核心推荐逻辑
│   │   ├── __init__.py
│   │   ├── recall/               # 召回模块
│   │   │   ├── item_cf.py
│   │   │   ├── hot_recall.py
│   │   │   ├── content_recall.py
│   │   │   └── merger.py
│   │   ├── ranking/              # 排序模块
│   │   │   ├── deepfm.py
│   │   │   └── ranker.py
│   │   ├── rerank/               # 重排模块
│   │   │   └── reranker.py
│   │   └── pipeline.py           # 推荐流水线
│   ├── models/                   # 数据模型
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── game.py
│   │   └── behavior.py
│   ├── services/                 # 业务服务
│   │   ├── __init__.py
│   │   ├── feature_service.py    # 特征服务
│   │   ├── user_service.py
│   │   └── game_service.py
│   └── utils/                    # 工具类
│       ├── __init__.py
│       ├── redis_client.py
│       └── logger.py
├── training/                     # 离线训练
│   ├── __init__.py
│   ├── data/                     # 数据处理
│   │   ├── sample_builder.py     # 样本构建
│   │   └── feature_eng.py        # 特征工程
│   ├── models/                   # 模型定义
│   │   ├── deepfm.py
│   │   ├── two_tower.py
│   │   └── din.py
│   ├── trainers/                 # 训练器
│   │   └── trainer.py
│   └── scripts/                  # 训练脚本
│       ├── train_deepfm.py
│       ├── train_item_cf.py
│       └── export_model.py
├── jobs/                         # 定时任务
│   ├── __init__.py
│   ├── update_hot_list.py        # 更新热门榜单
│   ├── update_similarity.py      # 更新相似度矩阵
│   └── scheduler.py              # 任务调度
├── tests/                        # 测试
│   ├── __init__.py
│   ├── test_recall.py
│   ├── test_ranking.py
│   └── test_api.py
├── scripts/                      # 部署脚本
│   ├── init_db.py
│   └── load_sample_data.py
├── docker/                       # Docker 配置
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 三、API 接口设计

### 3.1 推荐接口

```python
# GET /api/v1/recommend/games
# 获取个性化推荐列表

Request:
{
    "user_id": "string",         # 必填
    "scene": "home|slots|crash|live|similar",  # 必填
    "game_id": "string",         # 相似推荐时必填
    "page": 1,                   # 默认1
    "page_size": 20,             # 默认20, 最大50
    "exclude_played": true       # 是否排除最近玩过的游戏
}

Response:
{
    "code": 0,
    "message": "success",
    "data": {
        "games": [
            {
                "game_id": "game_001",
                "game_name": "Gates of Olympus",
                "category": "Slots",
                "sub_category": "Megaways",
                "provider": "Pragmatic Play",
                "thumbnail_url": "https://...",
                "rtp": 96.5,
                "volatility": "high",
                "score": 0.95,
                "recall_source": "item_cf",       # 召回来源
                "reason": "基于您对老虎机的喜好推荐"  # 推荐理由
            }
        ],
        "total": 100,
        "has_more": true,
        "request_id": "req_xxx"   # 用于日志追踪
    }
}
```

### 3.2 行为上报接口

```python
# POST /api/v1/behavior/track
# 记录用户行为

Request:
{
    "user_id": "string",
    "game_id": "string",
    "behavior_type": "view|click|play|bet|favorite|unfavorite",
    "duration": 300,              # 游戏时长(秒)，play时必填
    "bet_amount": 100.00,         # 投注金额，bet时必填
    "win_amount": 150.00,         # 赢取金额，bet时可选
    "context": {                  # 上下文信息
        "device": "mobile|desktop",
        "scene": "home|category|search",
        "position": 3,            # 展示位置
        "request_id": "req_xxx"   # 关联推荐请求
    }
}

Response:
{
    "code": 0,
    "message": "success"
}
```

### 3.3 管理接口

```python
# POST /api/v1/admin/boost
# 运营配置游戏权重

Request:
{
    "game_id": "string",
    "boost_weight": 1.5,          # 权重系数 0.5~2.0
    "start_time": "2026-01-18T00:00:00",
    "end_time": "2026-01-25T00:00:00"
}

# GET /api/v1/admin/metrics
# 获取系统指标

Response:
{
    "code": 0,
    "data": {
        "qps": 150,
        "p99_latency_ms": 45,
        "recall_coverage": 0.85,
        "cache_hit_rate": 0.92
    }
}
```

---

## 四、开发计划（分阶段）

### 4.1 总体时间线

```
┌────────────────────────────────────────────────────────────────────────┐
│                         开发时间线 (共6周)                               │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Phase 1: MVP (Week 1-2)                                              │
│  ═══════════════════════                                              │
│  ├── Day 1-2: 项目骨架 + 数据层                                        │
│  ├── Day 3-4: 召回模块 (Item-CF + 热门)                                │
│  ├── Day 5-6: 精排模块 (DeepFM)                                        │
│  ├── Day 7-8: API接口 + 重排                                          │
│  ├── Day 9-10: 联调测试 + 部署                                         │
│  └── ✅ 交付: 可运行的基础推荐系统                                      │
│                                                                        │
│  Phase 2: 功能完善 (Week 3-4)                                          │
│  ═════════════════════════                                            │
│  ├── Day 11-12: 冷启动策略                                             │
│  ├── Day 13-14: 内容召回 + 新游戏召回                                  │
│  ├── Day 15-16: 实时特征服务                                           │
│  ├── Day 17-18: 多样性重排 + 业务规则                                  │
│  └── ✅ 交付: 完整的推荐链路                                            │
│                                                                        │
│  Phase 3: 模型升级 (Week 5-6)                                          │
│  ═════════════════════════                                            │
│  ├── Day 19-21: 双塔模型 + FAISS索引                                   │
│  ├── Day 22-24: DIN模型(可选)                                          │
│  ├── Day 25-26: A/B测试框架                                            │
│  ├── Day 27-28: 监控告警 + 文档                                        │
│  └── ✅ 交付: 生产级推荐系统                                            │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Phase 1: MVP 详细计划 (Week 1-2)

#### Day 1-2: 项目骨架 + 数据层

**交付物:**
- 完整的项目结构
- 数据库表创建脚本
- 基础配置管理

**任务清单:**

```
□ 项目初始化
  ├── 创建项目结构 (如上述目录结构)
  ├── 配置 pyproject.toml / requirements.txt
  ├── 配置 pre-commit hooks (black, isort, flake8)
  └── 创建 .env 配置模板

□ 数据库设计与创建
  ├── game_info 表 (游戏基础信息)
  ├── user_profile 表 (用户画像)
  ├── user_behavior 表 (用户行为)
  └── 索引优化

□ 基础组件
  ├── FastAPI 应用初始化
  ├── SQLAlchemy 异步配置
  ├── Redis 连接池配置
  └── 日志配置 (结构化日志)

□ 示例数据
  ├── 导入游戏数据 (50-100款游戏)
  ├── 生成模拟用户数据 (1000用户)
  └── 生成模拟行为数据 (10万条)
```

**验收标准:**
- 数据库可正常连接
- FastAPI 启动正常，Swagger 文档可访问
- 示例数据导入成功

#### Day 3-4: 召回模块

**交付物:**
- Item-CF 召回服务
- 热门召回服务
- 召回合并去重

**核心代码示例:**

```python
# app/core/recall/item_cf.py
class ItemCFRecall:
    def __init__(self, redis_client, similarity_key_prefix="game:sim:"):
        self.redis = redis_client
        self.key_prefix = similarity_key_prefix
    
    async def recall(self, user_id: str, played_games: List[str], 
                     top_k: int = 100) -> List[Tuple[str, float]]:
        """
        基于用户历史行为的 Item-CF 召回
        """
        candidate_scores = defaultdict(float)
        
        # 获取用户最近玩过的游戏的相似游戏
        for game_id in played_games[-20:]:  # 最近20个
            sim_key = f"{self.key_prefix}{game_id}"
            similar_games = await self.redis.hgetall(sim_key)
            
            for sim_game_id, score in similar_games.items():
                if sim_game_id not in played_games:
                    candidate_scores[sim_game_id] += float(score)
        
        # 排序返回 Top-K
        ranked = sorted(candidate_scores.items(), 
                       key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
```

**验收标准:**
- Item-CF 召回接口响应时间 < 10ms
- 热门召回接口响应时间 < 5ms
- 召回结果去重正确

#### Day 5-6: 精排模块

**交付物:**
- DeepFM 模型训练脚本
- 模型推理服务
- 特征编码器

**核心代码示例:**

```python
# training/models/deepfm.py
import torch
import torch.nn as nn

class DeepFM(nn.Module):
    def __init__(self, feature_dims: Dict[str, int], 
                 embed_dim: int = 16, 
                 hidden_dims: List[int] = [128, 64]):
        super().__init__()
        
        self.feature_names = list(feature_dims.keys())
        self.embeddings = nn.ModuleDict({
            name: nn.Embedding(dim, embed_dim) 
            for name, dim in feature_dims.items()
        })
        
        # FM 一阶
        self.linear = nn.ModuleDict({
            name: nn.Embedding(dim, 1) 
            for name, dim in feature_dims.items()
        })
        
        # DNN
        dnn_input_dim = len(feature_dims) * embed_dim
        layers = []
        for hidden_dim in hidden_dims:
            layers.extend([
                nn.Linear(dnn_input_dim, hidden_dim),
                nn.ReLU(),
                nn.BatchNorm1d(hidden_dim),
                nn.Dropout(0.2)
            ])
            dnn_input_dim = hidden_dim
        self.dnn = nn.Sequential(*layers)
        self.dnn_output = nn.Linear(hidden_dims[-1], 1)
        
    def forward(self, x: Dict[str, torch.Tensor]) -> torch.Tensor:
        # 一阶部分
        linear_out = sum(self.linear[name](x[name]).squeeze(-1) 
                        for name in self.feature_names)
        
        # Embedding
        embeds = [self.embeddings[name](x[name]) 
                  for name in self.feature_names]
        embed_stack = torch.stack(embeds, dim=1)  # [B, F, E]
        
        # FM 二阶
        sum_square = embed_stack.sum(dim=1).pow(2)
        square_sum = embed_stack.pow(2).sum(dim=1)
        fm_out = 0.5 * (sum_square - square_sum).sum(dim=1)
        
        # DNN
        dnn_input = embed_stack.view(x[self.feature_names[0]].size(0), -1)
        dnn_out = self.dnn_output(self.dnn(dnn_input)).squeeze(-1)
        
        return torch.sigmoid(linear_out + fm_out + dnn_out)
```

**验收标准:**
- 模型训练完成，AUC > 0.70
- 单次推理延迟 < 20ms (100个候选)
- 模型可正常导出为 ONNX

#### Day 7-8: API接口 + 重排

**交付物:**
- 推荐 API 接口
- 行为上报接口
- 简单重排逻辑

**核心代码示例:**

```python
# app/api/recommend.py
from fastapi import APIRouter, Depends
from app.core.pipeline import RecommendationPipeline

router = APIRouter(prefix="/api/v1/recommend", tags=["recommend"])

@router.get("/games")
async def get_recommendations(
    user_id: str,
    scene: str = "home",
    game_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    pipeline: RecommendationPipeline = Depends(get_pipeline)
):
    request_id = generate_request_id()
    
    try:
        result = await pipeline.recommend(
            user_id=user_id,
            scene=scene,
            game_id=game_id,
            size=page_size,
            offset=(page - 1) * page_size
        )
        
        return {
            "code": 0,
            "message": "success",
            "data": {
                "games": result.games,
                "total": result.total,
                "has_more": result.has_more,
                "request_id": request_id
            }
        }
    except Exception as e:
        logger.error(f"Recommendation failed: {e}", request_id=request_id)
        # 降级到热门推荐
        return await fallback_to_hot(user_id, page_size)
```

**验收标准:**
- API 接口响应时间 P99 < 100ms
- 行为上报成功率 > 99.9%
- 重排后类目多样性符合预期

#### Day 9-10: 联调测试 + 部署

**交付物:**
- 端到端测试用例
- Docker 部署配置
- 基础监控

**Docker Compose 配置:**

```yaml
# docker/docker-compose.yml
version: '3.8'

services:
  app:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/rec
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  db:
    image: postgres:15
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: rec

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

volumes:
  postgres_data:
  redis_data:
```

**验收标准:**
- 完整推荐链路可正常运行
- Docker 容器启动正常
- 基础健康检查通过

### 4.3 Phase 2: 功能完善 (Week 3-4)

| 天数 | 任务 | 交付物 |
|-----|------|-------|
| Day 11-12 | 冷启动策略 | 新用户冷启动、新游戏冷启动 |
| Day 13-14 | 召回增强 | 内容召回、新游戏强制曝光 |
| Day 15-16 | 实时特征 | Session 特征、用户实时行为 |
| Day 17-18 | 重排优化 | MMR 多样性、业务规则引擎 |

### 4.4 Phase 3: 模型升级 (Week 5-6)

| 天数 | 任务 | 交付物 |
|-----|------|-------|
| Day 19-21 | 双塔模型 | 训练、FAISS 索引、在线召回 |
| Day 22-24 | DIN 模型(可选) | 序列特征、Attention 机制 |
| Day 25-26 | A/B 测试 | 分流框架、实验配置 |
| Day 27-28 | 监控完善 | Prometheus 指标、Grafana 面板 |

---

## 五、核心算法实现

### 5.1 Item-CF 相似度计算（离线）

```python
# training/scripts/train_item_cf.py
import pandas as pd
import numpy as np
from collections import defaultdict
from scipy.sparse import csr_matrix
from sklearn.metrics.pairwise import cosine_similarity
import redis

def compute_item_similarity(behaviors_df: pd.DataFrame, 
                           top_k: int = 50) -> Dict[str, Dict[str, float]]:
    """
    计算游戏相似度矩阵
    使用 IUF (Inverse User Frequency) 惩罚活跃用户
    """
    # 构建用户-游戏交互矩阵
    user_ids = behaviors_df['user_id'].unique()
    game_ids = behaviors_df['game_id'].unique()
    
    user_idx = {uid: i for i, uid in enumerate(user_ids)}
    game_idx = {gid: i for i, gid in enumerate(game_ids)}
    
    # 计算 IUF 权重
    user_game_count = behaviors_df.groupby('user_id').size()
    
    rows, cols, data = [], [], []
    for _, row in behaviors_df.iterrows():
        u_idx = user_idx[row['user_id']]
        g_idx = game_idx[row['game_id']]
        # IUF 权重: 1 / log(1 + 用户交互数)
        iuf_weight = 1.0 / np.log(1 + user_game_count[row['user_id']])
        rows.append(u_idx)
        cols.append(g_idx)
        data.append(iuf_weight)
    
    # 构建稀疏矩阵
    interaction_matrix = csr_matrix(
        (data, (rows, cols)), 
        shape=(len(user_ids), len(game_ids))
    )
    
    # 计算游戏相似度 (转置后计算列向量相似度)
    item_matrix = interaction_matrix.T  # [games, users]
    similarity = cosine_similarity(item_matrix, dense_output=False)
    
    # 提取 Top-K 相似游戏
    idx_to_game = {i: gid for gid, i in game_idx.items()}
    result = {}
    
    for i, gid in idx_to_game.items():
        sim_scores = similarity[i].toarray().flatten()
        # 排除自身
        sim_scores[i] = 0
        top_indices = np.argsort(sim_scores)[-top_k:][::-1]
        
        result[gid] = {
            idx_to_game[j]: float(sim_scores[j]) 
            for j in top_indices if sim_scores[j] > 0
        }
    
    return result


def save_to_redis(similarity: Dict[str, Dict[str, float]], 
                  redis_client: redis.Redis):
    """保存相似度到 Redis"""
    pipe = redis_client.pipeline()
    
    for game_id, similar_games in similarity.items():
        key = f"game:sim:{game_id}"
        pipe.delete(key)
        if similar_games:
            pipe.hset(key, mapping=similar_games)
        pipe.expire(key, 86400 * 7)  # 7天过期
    
    pipe.execute()
```

### 5.2 推荐流水线

```python
# app/core/pipeline.py
from dataclasses import dataclass
from typing import List, Optional
import asyncio

@dataclass
class RecommendResult:
    games: List[dict]
    total: int
    has_more: bool

class RecommendationPipeline:
    def __init__(self, 
                 recall_modules: List[BaseRecall],
                 ranker: BaseRanker,
                 reranker: BaseReranker,
                 feature_service: FeatureService):
        self.recall_modules = recall_modules
        self.ranker = ranker
        self.reranker = reranker
        self.feature_service = feature_service
    
    async def recommend(self, user_id: str, scene: str,
                       game_id: Optional[str] = None,
                       size: int = 20, 
                       offset: int = 0) -> RecommendResult:
        """
        完整推荐流程: 召回 → 粗排(可选) → 精排 → 重排
        """
        # 1. 获取用户特征
        user_feature = await self.feature_service.get_user_feature(user_id)
        
        # 2. 多路召回 (并发执行)
        recall_tasks = [
            module.recall(user_id, user_feature, scene)
            for module in self.recall_modules
        ]
        recall_results = await asyncio.gather(*recall_tasks)
        
        # 3. 合并去重
        candidates = self._merge_and_dedupe(recall_results)
        
        if not candidates:
            return RecommendResult(games=[], total=0, has_more=False)
        
        # 4. 精排
        ranked_candidates = await self.ranker.rank(
            user_feature, candidates, scene
        )
        
        # 5. 重排
        reranked = await self.reranker.rerank(
            ranked_candidates, 
            user_feature,
            scene
        )
        
        # 6. 分页返回
        total = len(reranked)
        games = reranked[offset:offset + size]
        
        return RecommendResult(
            games=games,
            total=total,
            has_more=offset + size < total
        )
    
    def _merge_and_dedupe(self, recall_results: List[List[dict]]) -> List[dict]:
        """合并多路召回结果并去重，保留最高分"""
        seen = {}
        for results in recall_results:
            for item in results:
                game_id = item['game_id']
                if game_id not in seen or item['score'] > seen[game_id]['score']:
                    seen[game_id] = item
        
        return sorted(seen.values(), key=lambda x: x['score'], reverse=True)
```

---

## 六、监控与运维

### 6.1 核心监控指标

```python
# app/utils/metrics.py
from prometheus_client import Counter, Histogram, Gauge

# 请求指标
REQUEST_COUNT = Counter(
    'rec_request_total', 
    'Total recommendation requests',
    ['scene', 'status']
)

REQUEST_LATENCY = Histogram(
    'rec_request_latency_seconds',
    'Request latency in seconds',
    ['scene'],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

# 召回指标
RECALL_COUNT = Gauge(
    'rec_recall_candidate_count',
    'Number of candidates from recall',
    ['source']
)

# 缓存指标
CACHE_HIT_RATE = Gauge(
    'rec_cache_hit_rate',
    'Cache hit rate'
)

# 模型指标
MODEL_INFERENCE_LATENCY = Histogram(
    'rec_model_inference_seconds',
    'Model inference latency',
    ['model_name']
)
```

### 6.2 告警规则

| 级别 | 条件 | 动作 |
|-----|------|-----|
| P0 | 服务可用性 < 99% | 立即响应 + 电话 |
| P0 | P99 延迟 > 500ms | 立即响应 |
| P1 | P99 延迟 > 200ms | 30分钟内处理 |
| P1 | 错误率 > 1% | 30分钟内处理 |
| P2 | 缓存命中率 < 80% | 当日处理 |
| P2 | 召回覆盖率 < 70% | 当日处理 |

---

## 七、总结

### 7.1 MVP 阶段核心交付

| 模块 | 功能 | 技术实现 |
|-----|------|---------|
| 召回 | Item-CF + 热门 | Redis 存储、并发查询 |
| 精排 | DeepFM | PyTorch 训练、ONNX 推理 |
| 重排 | 规则打散 | 类目/提供商间隔 |
| API | 推荐 + 行为上报 | FastAPI 异步 |
| 部署 | 容器化 | Docker Compose |

### 7.2 后续迭代方向

1. **召回增强**: 双塔模型 + FAISS 向量召回
2. **精排升级**: DIN 模型支持用户行为序列
3. **多目标优化**: pCTR × pCVR 联合预估
4. **实时特征**: Session 级实时特征
5. **A/B 测试**: 分流实验框架

### 7.3 风险与应对

| 风险 | 影响 | 应对措施 |
|-----|------|---------|
| 冷启动效果差 | 新用户体验 | 热门榜单兜底 + 快速学习 |
| 模型推理延迟 | 响应时间 | ONNX 优化 + 批量推理 |
| 数据稀疏 | 召回质量 | 内容召回补充 |
| 系统故障 | 服务可用性 | 降级到热门 + 缓存兜底 |

---

如果您需要我进一步展开任何部分（如具体的模型代码实现、数据库详细设计、部署脚本等），请告诉我。由于我目前处于 Ask 模式，如需我实际创建代码文件，请切换到 Agent 模式。