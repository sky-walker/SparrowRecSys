# 推荐算法模块数据表设计

> **文档目的**：定义推荐系统算法模块直接消费的数据表结构，供大数据工程师进行ETL开发。
> 
> **适用场景**：特征处理、召回、粗排、精排、重排等核心推荐链路。

---

## 一、设计原则

### 1.1 核心思想

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        算法模块数据消费架构                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   业务系统原始数据                                                       │
│   (用户表、游戏表、行为日志...)                                          │
│         │                                                               │
│         │  ETL (大数据工程师负责)                                        │
│         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │              算法模块专用数据表 (本文档定义)                       │  │
│   │                                                                   │  │
│   │   MySQL (离线特征表)          Redis (实时特征+召回数据)            │  │
│   │   ├── 用户特征表              ├── 用户实时特征                     │  │
│   │   ├── 游戏特征表              ├── 用户行为序列                     │  │
│   │   ├── 游戏相似度表            ├── 热门游戏榜单                     │  │
│   │   ├── 召回候选表              ├── 游戏相似矩阵                     │  │
│   │   └── 推荐日志表              └── Embedding向量                    │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│         │                                                               │
│         │  直接读取                                                      │
│         ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │              推荐算法模块                                          │  │
│   │   召回 → 粗排 → 精排 → 重排                                       │  │
│   └─────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 设计要求

| 要求 | 说明 |
|------|------|
| **高QPS支持** | 所有表需支持 QPS > 1000 的在线查询 |
| **低延迟** | 单表查询 P99 < 5ms |
| **特征就绪** | 特征已预处理，算法模块直接使用，无需二次计算 |
| **版本控制** | 支持特征版本管理，便于A/B测试 |

### 1.3 数据更新频率分类

| 类型 | 更新频率 | 存储位置 | 说明 |
|------|----------|----------|------|
| **实时特征** | 秒级~分钟级 | Redis | Session特征、实时行为序列 |
| **近实时特征** | 小时级 | Redis/MySQL | 热门榜单、统计指标 |
| **离线特征** | T+1 | MySQL | 用户画像、游戏统计特征 |
| **模型产物** | 每日/每周 | MySQL+Redis | Embedding、相似度矩阵 |

---

## 二、MySQL 表结构定义

### 2.1 用户特征表 (algo_user_features)

**用途**：存储用户离线特征，供精排模型使用。

**更新频率**：T+1 离线更新

**使用场景**：精排模型的用户侧特征输入

```sql
CREATE TABLE algo_user_features (
    -- 主键
    user_id VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '用户ID',
    
    -- ============ 用户基础特征 ============
    -- 生命周期
    lifecycle_stage TINYINT UNSIGNED NOT NULL DEFAULT 0 
        COMMENT '生命周期: 0-new 1-growth 2-active 3-mature 4-decline 5-churn',
    register_days INT UNSIGNED DEFAULT 0 COMMENT '注册天数',
    active_days_7d TINYINT UNSIGNED DEFAULT 0 COMMENT '近7天活跃天数',
    active_days_30d TINYINT UNSIGNED DEFAULT 0 COMMENT '近30天活跃天数',
    
    -- 设备与渠道 (用于冷启动)
    register_channel_id SMALLINT UNSIGNED DEFAULT 0 COMMENT '注册渠道ID (已编码)',
    register_device_id TINYINT UNSIGNED DEFAULT 0 COMMENT '注册设备ID: 0-unknown 1-ios 2-android 3-web',
    
    -- ============ 用户偏好特征 ============
    -- 类目偏好 (归一化概率分布, 4个类目)
    pref_category_slots DECIMAL(4,3) DEFAULT 0.250 COMMENT 'Slots偏好度 0-1',
    pref_category_crash DECIMAL(4,3) DEFAULT 0.250 COMMENT 'Crash偏好度 0-1',
    pref_category_live DECIMAL(4,3) DEFAULT 0.250 COMMENT 'Live偏好度 0-1',
    pref_category_virtual DECIMAL(4,3) DEFAULT 0.250 COMMENT 'Virtual偏好度 0-1',
    
    -- Top3偏好提供商 (ID编码)
    pref_provider_1 SMALLINT UNSIGNED DEFAULT 0 COMMENT '最偏好提供商ID',
    pref_provider_2 SMALLINT UNSIGNED DEFAULT 0 COMMENT '第2偏好提供商ID',
    pref_provider_3 SMALLINT UNSIGNED DEFAULT 0 COMMENT '第3偏好提供商ID',
    
    -- 风险偏好 (基于波动性选择计算)
    risk_preference TINYINT UNSIGNED DEFAULT 1 COMMENT '风险偏好: 0-low 1-medium 2-high',
    risk_score DECIMAL(4,3) DEFAULT 0.500 COMMENT '风险偏好分数 0-1',
    
    -- ============ 用户行为统计特征 ============
    -- 总量统计
    total_play_count INT UNSIGNED DEFAULT 0 COMMENT '累计游戏次数',
    total_play_duration BIGINT UNSIGNED DEFAULT 0 COMMENT '累计游戏时长(秒)',
    total_bet_amount DECIMAL(15,2) DEFAULT 0.00 COMMENT '累计投注金额',
    total_win_amount DECIMAL(15,2) DEFAULT 0.00 COMMENT '累计赢取金额',
    
    -- 近期统计 (7天)
    play_count_7d INT UNSIGNED DEFAULT 0 COMMENT '7天游戏次数',
    play_duration_7d INT UNSIGNED DEFAULT 0 COMMENT '7天游戏时长(秒)',
    bet_amount_7d DECIMAL(15,2) DEFAULT 0.00 COMMENT '7天投注金额',
    distinct_games_7d SMALLINT UNSIGNED DEFAULT 0 COMMENT '7天玩过的不同游戏数',
    
    -- 投注模式
    bet_pattern TINYINT UNSIGNED DEFAULT 0 COMMENT '投注模式: 0-small_frequent 1-large_rare 2-mixed',
    avg_bet_amount DECIMAL(10,2) DEFAULT 0.00 COMMENT '平均单次投注',
    avg_session_duration INT UNSIGNED DEFAULT 0 COMMENT '平均会话时长(秒)',
    
    -- ============ 交叉统计特征 (预计算) ============
    -- 各类目CTR (用户在各类目的历史点击率)
    ctr_category_slots DECIMAL(5,4) DEFAULT 0.0000 COMMENT 'Slots类目CTR',
    ctr_category_crash DECIMAL(5,4) DEFAULT 0.0000 COMMENT 'Crash类目CTR',
    ctr_category_live DECIMAL(5,4) DEFAULT 0.0000 COMMENT 'Live类目CTR',
    ctr_category_virtual DECIMAL(5,4) DEFAULT 0.0000 COMMENT 'Virtual类目CTR',
    
    -- ============ 版本控制 ============
    feature_version VARCHAR(16) DEFAULT 'v1.0' COMMENT '特征版本',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='用户特征表 - 算法模块专用';

-- 索引：主键查询为主，无需额外索引
```

**ETL要求（给大数据工程师）：**
- 数据来源：用户主表、用户行为表
- 更新时间：每日凌晨 T+1 全量更新
- 偏好计算：基于近30天行为加权计算，时间衰减因子 0.95^days
- CTR计算：曝光数 >= 10 时计算，否则使用全局平均值填充

---

### 2.2 游戏特征表 (algo_game_features)

**用途**：存储游戏离线特征，供召回过滤和精排模型使用。

**更新频率**：小时级更新热度统计，T+1更新其他特征

**使用场景**：
- 热门召回：按 `hot_score_*` 排序
- 内容召回：按类目/提供商/属性过滤
- 精排模型：游戏侧特征输入
- 重排过滤：按 `status`、`is_blocked` 过滤

```sql
CREATE TABLE algo_game_features (
    -- 主键
    game_id VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '游戏ID',

    -- ============ 游戏基础属性 ============
    category_id TINYINT UNSIGNED NOT NULL DEFAULT 0
        COMMENT '类目ID: 0-unknown 1-slots 2-crash 3-live 4-virtual',
    provider_id SMALLINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '提供商ID (已编码)',

    -- 核心属性 (已数值化)
    rtp DECIMAL(5,2) DEFAULT NULL COMMENT 'RTP返还率 (如96.50)',
    volatility TINYINT UNSIGNED DEFAULT 1 COMMENT '波动性: 0-low 1-medium 2-high 3-very_high',
    volatility_score DECIMAL(3,2) DEFAULT 2.50 COMMENT '波动性数值 1.00-5.00',

    -- 投注范围
    min_bet DECIMAL(10,2) DEFAULT 0.10 COMMENT '最小投注',
    max_bet DECIMAL(10,2) DEFAULT 1000.00 COMMENT '最大投注',

    -- ============ 游戏状态 ============
    status TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '状态: 0-下线 1-上线 2-维护',
    is_new TINYINT(1) DEFAULT 0 COMMENT '是否新游戏(7天内上线)',
    is_featured TINYINT(1) DEFAULT 0 COMMENT '是否运营推荐',
    is_jackpot TINYINT(1) DEFAULT 0 COMMENT '是否有累积奖池',

    -- 生命周期
    launch_days INT UNSIGNED DEFAULT 0 COMMENT '上线天数',
    lifecycle_stage TINYINT UNSIGNED DEFAULT 0 COMMENT '生命周期: 0-new 1-growth 2-mature 3-decline',

    -- ============ 多值属性编码 ============
    -- 主题标签 (BitMap编码, 最多支持64个主题)
    themes_bitmap BIGINT UNSIGNED DEFAULT 0 COMMENT '主题标签位图',
    -- 特性标签 (BitMap编码)
    features_bitmap BIGINT UNSIGNED DEFAULT 0 COMMENT '特性标签位图 (megaways/free_spins等)',

    -- Top3主题ID (用于快速匹配)
    theme_1 SMALLINT UNSIGNED DEFAULT 0 COMMENT '主要主题ID',
    theme_2 SMALLINT UNSIGNED DEFAULT 0 COMMENT '次要主题ID',
    theme_3 SMALLINT UNSIGNED DEFAULT 0 COMMENT '第三主题ID',

    -- ============ 热度统计特征 (小时级更新) ============
    -- 热度分数 (归一化到0-1)
    hot_score_1h DECIMAL(6,5) DEFAULT 0.00000 COMMENT '1小时热度分数',
    hot_score_24h DECIMAL(6,5) DEFAULT 0.00000 COMMENT '24小时热度分数',
    hot_score_7d DECIMAL(6,5) DEFAULT 0.00000 COMMENT '7天热度分数',

    -- 原始统计 (用于排序)
    play_count_1h INT UNSIGNED DEFAULT 0 COMMENT '1小时游戏次数',
    play_count_24h INT UNSIGNED DEFAULT 0 COMMENT '24小时游戏次数',
    play_count_7d INT UNSIGNED DEFAULT 0 COMMENT '7天游戏次数',
    unique_players_7d INT UNSIGNED DEFAULT 0 COMMENT '7天独立玩家数',

    -- ============ 效果指标 (T+1更新) ============
    ctr_7d DECIMAL(6,4) DEFAULT 0.0000 COMMENT '7天点击率',
    cvr_7d DECIMAL(6,4) DEFAULT 0.0000 COMMENT '7天转化率(点击→游戏)',
    avg_session_duration INT UNSIGNED DEFAULT 0 COMMENT '平均游戏时长(秒)',
    avg_bet_amount DECIMAL(10,2) DEFAULT 0.00 COMMENT '平均单次投注',

    -- 评分
    avg_rating DECIMAL(3,2) DEFAULT 0.00 COMMENT '平均评分 0-5',
    favorite_count INT UNSIGNED DEFAULT 0 COMMENT '收藏数',

    -- ============ 运营权重 ============
    boost_weight DECIMAL(4,2) DEFAULT 1.00 COMMENT '运营加权 0.50-2.00',

    -- ============ 版本控制 ============
    feature_version VARCHAR(16) DEFAULT 'v1.0' COMMENT '特征版本',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏特征表 - 算法模块专用';

-- 召回查询索引
CREATE INDEX idx_category_hot ON algo_game_features(category_id, status, hot_score_7d DESC);
CREATE INDEX idx_provider_hot ON algo_game_features(provider_id, status, hot_score_7d DESC);
CREATE INDEX idx_new_games ON algo_game_features(is_new, status, launch_days);
CREATE INDEX idx_featured ON algo_game_features(is_featured, status, boost_weight DESC);
CREATE INDEX idx_status ON algo_game_features(status);
```

**ETL要求（给大数据工程师）：**
- 热度分数：需归一化到0-1范围，公式：`score = log(1 + count) / log(1 + max_count)`
- 主题/特性位图：需要提供编码映射表
- 小时级任务：仅更新 `hot_score_*` 和 `play_count_*` 字段
- 状态同步：与业务系统保持一致

---

### 2.3 游戏相似度表 (algo_game_similarity)

**用途**：存储预计算的游戏相似度矩阵，供 Item-CF 召回使用。

**更新频率**：T+1 离线更新

**使用场景**：
- Item-CF召回：根据用户历史游戏查找相似游戏
- 相似推荐：游戏详情页的"相似游戏"推荐

```sql
CREATE TABLE algo_game_similarity (
    -- 联合主键
    game_id VARCHAR(64) NOT NULL COMMENT '源游戏ID',
    similar_game_id VARCHAR(64) NOT NULL COMMENT '相似游戏ID',

    -- 相似度信息
    similarity_score DECIMAL(6,5) NOT NULL COMMENT '相似度分数 0-1',
    similarity_rank SMALLINT UNSIGNED NOT NULL COMMENT '相似度排名 (1为最相似)',

    -- 相似度类型
    similarity_type TINYINT UNSIGNED DEFAULT 0
        COMMENT '类型: 0-itemcf 1-content 2-embedding',

    -- 版本控制
    version VARCHAR(16) DEFAULT 'v1.0' COMMENT '模型版本',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (game_id, similar_game_id, similarity_type)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏相似度表 - Item-CF召回专用';

-- 召回查询索引 (按源游戏+类型查询，按排名排序)
CREATE INDEX idx_recall ON algo_game_similarity(game_id, similarity_type, similarity_rank);
```

**ETL要求（给大数据工程师）：**
- 每个游戏保留 Top 50 相似游戏
- Item-CF相似度计算使用 IUF 加权余弦相似度
- 同时计算类目内相似度和跨类目相似度

---

### 2.4 用户召回候选表 (algo_user_recall)

**用途**：存储离线预计算的用户个性化召回候选集（非实时类召回）。

**更新频率**：T+1 离线更新

**使用场景**：
- Item-CF召回：预计算的协同过滤结果
- Embedding召回：预计算的向量召回结果
- 内容召回：基于用户画像预计算的匹配结果

```sql
CREATE TABLE algo_user_recall (
    -- 联合主键
    user_id VARCHAR(64) NOT NULL COMMENT '用户ID',
    game_id VARCHAR(64) NOT NULL COMMENT '游戏ID',
    recall_type TINYINT UNSIGNED NOT NULL
        COMMENT '召回类型: 0-itemcf 1-embedding 2-content',

    -- 召回信息
    recall_score DECIMAL(8,6) NOT NULL COMMENT '召回分数 0-1',
    recall_rank SMALLINT UNSIGNED NOT NULL COMMENT '召回排名',

    -- 召回原因 (用于解释)
    recall_reason VARCHAR(128) DEFAULT NULL
        COMMENT '召回原因 (如: similar_to:gate_of_olympus)',

    -- 版本控制
    version VARCHAR(16) DEFAULT 'v1.0' COMMENT '模型版本',
    expire_date DATE DEFAULT NULL COMMENT '过期日期',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (user_id, game_id, recall_type)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='用户召回候选表 - 离线召回预计算';

-- 召回查询索引
CREATE INDEX idx_user_recall ON algo_user_recall(user_id, recall_type, recall_rank);
-- 过期清理索引
CREATE INDEX idx_expire ON algo_user_recall(expire_date);
```

**ETL要求（给大数据工程师）：**
- 每个用户每种召回类型保留 Top 100 候选
- 过期时间设为 T+2（保留2天）
- 需要过滤掉用户已玩过的游戏

---

### 2.5 推荐效果日志表 (algo_recommendation_log)

**用途**：记录推荐请求和用户反馈，用于A/B测试和模型效果评估。

**更新频率**：实时写入

**使用场景**：
- A/B测试分析
- 模型效果评估（离线计算CTR/CVR）
- 召回源效果对比

```sql
CREATE TABLE algo_recommendation_log (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT,
    request_id VARCHAR(64) NOT NULL COMMENT '请求唯一ID',

    -- 用户信息
    user_id VARCHAR(64) NOT NULL COMMENT '用户ID',
    user_lifecycle TINYINT UNSIGNED DEFAULT 0 COMMENT '用户生命周期阶段（快照）',

    -- 请求上下文
    scene VARCHAR(32) NOT NULL COMMENT '场景: home/category/similar/search',
    device_type TINYINT UNSIGNED DEFAULT 0 COMMENT '设备: 0-unknown 1-ios 2-android 3-web',
    request_time DATETIME NOT NULL COMMENT '请求时间',

    -- A/B测试
    experiment_id VARCHAR(64) DEFAULT NULL COMMENT '实验ID',
    experiment_group VARCHAR(32) DEFAULT NULL COMMENT '实验分组: control/treatment',
    bucket_id SMALLINT UNSIGNED DEFAULT NULL COMMENT '分桶ID',

    -- 推荐结果
    recommended_games VARCHAR(2048) NOT NULL COMMENT '推荐游戏列表 (JSON数组)',
    recommended_count TINYINT UNSIGNED DEFAULT 0 COMMENT '推荐游戏数量',

    -- 各路召回统计
    recall_stats VARCHAR(512) DEFAULT NULL
        COMMENT '召回统计JSON: {"itemcf":10,"hot":15,"embedding":8...}',

    -- 性能指标
    total_latency_ms SMALLINT UNSIGNED DEFAULT 0 COMMENT '总耗时(ms)',
    recall_latency_ms SMALLINT UNSIGNED DEFAULT 0 COMMENT '召回耗时(ms)',
    rank_latency_ms SMALLINT UNSIGNED DEFAULT 0 COMMENT '排序耗时(ms)',

    -- 用户反馈 (后续回填)
    clicked_games VARCHAR(512) DEFAULT NULL COMMENT '点击的游戏 (JSON数组)',
    played_games VARCHAR(512) DEFAULT NULL COMMENT '开始游戏的游戏 (JSON数组)',
    click_count TINYINT UNSIGNED DEFAULT 0 COMMENT '点击数',
    play_count TINYINT UNSIGNED DEFAULT 0 COMMENT '游戏数',

    -- 分区键
    log_date DATE NOT NULL COMMENT '日志日期',

    PRIMARY KEY (id, log_date),
    UNIQUE KEY uk_request (request_id, log_date)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='推荐效果日志表'
PARTITION BY RANGE (TO_DAYS(log_date)) (
    PARTITION p20260118 VALUES LESS THAN (TO_DAYS('2026-01-19')),
    PARTITION p20260119 VALUES LESS THAN (TO_DAYS('2026-01-20')),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);

-- 分析查询索引
CREATE INDEX idx_user_time ON algo_recommendation_log(user_id, request_time);
CREATE INDEX idx_experiment ON algo_recommendation_log(experiment_id, experiment_group, log_date);
CREATE INDEX idx_scene ON algo_recommendation_log(scene, log_date);
```

**数据管理：**
- 日志保留30天，过期分区自动清理
- 用户反馈需要异步回填（用户行为发生后更新）

---

## 三、Redis 数据结构定义

> Redis 用于存储实时特征和高频访问的召回数据，所有 Key 需设置合理的 TTL。

### 3.1 用户实时特征 (Hash)

**用途**：存储用户当前Session的实时特征，供精排模型使用。

**更新频率**：实时（每次用户行为触发更新）

**使用场景**：精排模型的实时特征输入

```
Key: algo:user:realtime:{user_id}
Type: Hash
TTL: 30分钟（无活动自动过期）

Fields:
  session_id          STRING    当前会话ID
  session_start_ts    INT       会话开始时间戳
  session_duration    INT       当前会话时长(秒)

  # 本次会话行为计数
  view_count          INT       本次会话浏览次数
  click_count         INT       本次会话点击次数
  play_count          INT       本次会话游戏次数

  # 本次会话已交互游戏 (用于去重)
  viewed_games        STRING    JSON数组 ["game1","game2"]
  clicked_games       STRING    JSON数组
  played_games        STRING    JSON数组

  # 上下文特征
  last_action_type    STRING    最后行为类型: view/click/play
  last_action_ts      INT       最后行为时间戳
  last_game_id        STRING    最后交互的游戏ID
  last_category_id    INT       最后交互的类目ID

  # 设备信息
  device_type         INT       设备类型: 1-ios 2-android 3-web
  platform_version    STRING    平台版本
```

**写入示例（大数据工程师参考）：**
```python
redis.hset("algo:user:realtime:u123", mapping={
    "session_id": "sess_abc123",
    "session_start_ts": 1737216000,
    "view_count": 5,
    "click_count": 2,
    "play_count": 1,
    "viewed_games": '["game1","game2","game3"]',
    "last_action_type": "play",
    "last_game_id": "gate_of_olympus",
    "device_type": 1
})
redis.expire("algo:user:realtime:u123", 1800)
```

---

### 3.2 用户行为序列 (List)

**用途**：存储用户近期行为序列，供 DIN 模型的 Attention 机制使用。

**更新频率**：实时（每次用户行为追加）

**使用场景**：
- DIN模型：计算候选游戏与历史行为的注意力权重
- Item-CF召回：获取用户最近交互的游戏

```
Key: algo:user:behavior_seq:{user_id}
Type: List (LPUSH, 最新在前)
TTL: 7天
Max Length: 50 (使用 LTRIM 保持长度)

Value: JSON格式的行为记录
{
  "game_id": "gate_of_olympus",
  "category_id": 1,
  "action_type": "play",      # view/click/play
  "duration": 300,            # 游戏时长(秒), 仅play有值
  "timestamp": 1737216000
}
```

**写入示例：**
```python
behavior = {
    "game_id": "gate_of_olympus",
    "category_id": 1,
    "action_type": "play",
    "duration": 300,
    "timestamp": 1737216000
}
redis.lpush("algo:user:behavior_seq:u123", json.dumps(behavior))
redis.ltrim("algo:user:behavior_seq:u123", 0, 49)  # 保留最近50条
redis.expire("algo:user:behavior_seq:u123", 604800)  # 7天
```

---

### 3.3 热门游戏榜单 (Sorted Set)

**用途**：多维度热门游戏榜单，供热门召回使用。

**更新频率**：分钟级（实时热门）/ 小时级（其他维度）

**使用场景**：热门召回

```
Key Patterns:
  algo:hot:global              # 全局热门
  algo:hot:category:{cat_id}   # 分类热门 (1-slots, 2-crash, 3-live, 4-virtual)
  algo:hot:provider:{prov_id}  # 提供商热门
  algo:hot:period:{period}     # 时段热门 (morning/afternoon/evening/night)
  algo:hot:new                 # 新游戏热门

Type: Sorted Set
Score: 热度分数 (归一化到 0-10000 整数)
Member: game_id
TTL: 1小时（实时热门）/ 24小时（其他）
```

**写入示例：**
```python
# 更新全局热门
redis.zadd("algo:hot:global", {
    "gate_of_olympus": 9500,
    "aviator": 8800,
    "sweet_bonanza": 8200
})
redis.expire("algo:hot:global", 3600)

# 读取热门召回
hot_games = redis.zrevrange("algo:hot:global", 0, 29, withscores=True)
```

---

### 3.4 游戏相似矩阵缓存 (Hash)

**用途**：缓存游戏相似度矩阵，加速 Item-CF 召回查询。

**更新频率**：T+1（从 MySQL 同步）

**使用场景**：Item-CF召回

```
Key: algo:game:similar:{game_id}
Type: Hash
TTL: 24小时

Field: similar_game_id
Value: similarity_score (float string, 保留5位小数)
```

**写入示例：**
```python
# 从 MySQL 同步到 Redis
redis.hset("algo:game:similar:gate_of_olympus", mapping={
    "sweet_bonanza": "0.85123",
    "starlight_princess": "0.78456",
    "gates_of_olympus_1000": "0.92789"
})
redis.expire("algo:game:similar:gate_of_olympus", 86400)
```

---

### 3.5 Embedding 向量存储 (String)

**用途**：存储用户和游戏的 Embedding 向量，供向量召回使用。

**更新频率**：
- 游戏Embedding：每周更新
- 用户Embedding：T+1更新

**使用场景**：Embedding召回（配合 FAISS 索引）

```
Key Patterns:
  algo:emb:user:{user_id}    # 用户Embedding
  algo:emb:game:{game_id}    # 游戏Embedding

Type: String (二进制存储)
Value: 64维 float32 向量 = 256 bytes
TTL: 用户7天 / 游戏30天
```

**读写示例：**
```python
import numpy as np

# 写入
user_emb = np.random.randn(64).astype(np.float32)
redis.set("algo:emb:user:u123", user_emb.tobytes(), ex=604800)

# 读取
emb_bytes = redis.get("algo:emb:user:u123")
if emb_bytes:
    user_emb = np.frombuffer(emb_bytes, dtype=np.float32)
```

---

### 3.6 新游戏曝光统计 (Hash)

**用途**：记录新游戏的曝光和点击数据，用于 Thompson Sampling 探索。

**更新频率**：实时更新

**使用场景**：新游戏召回（冷启动探索）

```
Key: algo:newgame:stats:{game_id}
Type: Hash
TTL: 30天

Fields:
  impression_count    INT    曝光次数
  click_count         INT    点击次数
  play_count          INT    游戏次数
  alpha               FLOAT  Beta分布参数α (成功次数+1)
  beta                FLOAT  Beta分布参数β (失败次数+1)
  launch_date         STRING 上线日期 YYYY-MM-DD
```

**Thompson Sampling 使用：**
```python
import numpy as np

# 读取统计
stats = redis.hgetall("algo:newgame:stats:new_game_1")
alpha = float(stats.get("alpha", 1))
beta = float(stats.get("beta", 1))

# 采样
sampled_score = np.random.beta(alpha, beta)
```

---

### 3.7 推荐结果缓存 (String)

**用途**：缓存用户推荐结果，避免短时间内重复计算。

**更新频率**：按需写入

**使用场景**：推荐结果缓存

```
Key: algo:rec:cache:{user_id}:{scene}
Type: String (JSON)
TTL: 5分钟（首页）/ 10分钟（类目页）

Value:
{
  "request_id": "req_abc123",
  "games": [
    {"game_id": "gate_of_olympus", "score": 0.95, "source": "hot"},
    {"game_id": "aviator", "score": 0.88, "source": "itemcf"}
  ],
  "generated_at": 1737216000,
  "experiment_id": "exp_001",
  "version": "v1.0"
}
```

---

## 四、推荐链路数据流

### 4.1 各模块数据依赖

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           推荐链路数据流                                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  用户请求                                                                        │
│     │                                                                           │
│     ▼                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        召回层 (Recall)                                    │   │
│  │                                                                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │   │
│  │  │  热门召回    │  │  Item-CF    │  │ Embedding   │  │  内容召回    │     │   │
│  │  │             │  │   召回      │  │   召回      │  │             │     │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │   │
│  │         │                │                │                │            │   │
│  │  Redis:hot:*      Redis:similar   Redis:emb:*      MySQL:user_features  │   │
│  │                   MySQL:similarity MySQL:user_recall                     │   │
│  │                   MySQL:user_recall                                      │   │
│  │                                                                           │   │
│  │  ┌─────────────┐  ┌─────────────┐                                        │   │
│  │  │  新游戏召回  │  │  个性化召回  │                                        │   │
│  │  │             │  │  (续玩/收藏) │                                        │   │
│  │  └──────┬──────┘  └──────┬──────┘                                        │   │
│  │         │                │                                               │   │
│  │  Redis:newgame:*  Redis:behavior_seq                                     │   │
│  │  MySQL:game_features                                                     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│     │                                                                           │
│     ▼ (~100 candidates)                                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        粗排层 (Pre-Rank)                                  │   │
│  │                                                                           │   │
│  │  数据依赖:                                                                │   │
│  │  - MySQL: algo_game_features (游戏特征)                                   │   │
│  │  - Redis: algo:user:realtime (用户实时特征)                               │   │
│  │                                                                           │   │
│  │  模型: 轻量双塔模型，快速打分                                              │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│     │                                                                           │
│     ▼ (~30 candidates)                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        精排层 (Rank)                                      │   │
│  │                                                                           │   │
│  │  数据依赖:                                                                │   │
│  │  - MySQL: algo_user_features (用户离线特征)                               │   │
│  │  - MySQL: algo_game_features (游戏离线特征)                               │   │
│  │  - Redis: algo:user:realtime (用户实时特征)                               │   │
│  │  - Redis: algo:user:behavior_seq (用户行为序列 - DIN)                     │   │
│  │                                                                           │   │
│  │  模型: DeepFM / DIN                                                       │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│     │                                                                           │
│     ▼ (~15 candidates)                                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        重排层 (Re-Rank)                                   │   │
│  │                                                                           │   │
│  │  数据依赖:                                                                │   │
│  │  - MySQL: algo_game_features (类目/提供商信息 - 多样性)                   │   │
│  │  - Redis: algo:user:realtime.played_games (已玩过滤)                      │   │
│  │                                                                           │   │
│  │  规则: 多样性打散、运营置顶、已玩过滤                                      │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│     │                                                                           │
│     ▼ (~10 results)                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        日志记录                                           │   │
│  │                                                                           │   │
│  │  写入: MySQL algo_recommendation_log                                      │   │
│  │  缓存: Redis algo:rec:cache:{user_id}:{scene}                            │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 数据表使用场景汇总

| 表/Key | 召回 | 粗排 | 精排 | 重排 | 日志 |
|--------|------|------|------|------|------|
| **MySQL: algo_user_features** | ✓(内容) | | ✓ | | |
| **MySQL: algo_game_features** | ✓(热门/新游戏) | ✓ | ✓ | ✓ | |
| **MySQL: algo_game_similarity** | ✓(Item-CF) | | | | |
| **MySQL: algo_user_recall** | ✓(预计算) | | | | |
| **MySQL: algo_recommendation_log** | | | | | ✓ |
| **Redis: algo:user:realtime** | | ✓ | ✓ | ✓ | |
| **Redis: algo:user:behavior_seq** | ✓(Item-CF) | | ✓(DIN) | | |
| **Redis: algo:hot:*** | ✓(热门) | | | | |
| **Redis: algo:game:similar** | ✓(Item-CF) | | | | |
| **Redis: algo:emb:*** | ✓(Embedding) | | | | |
| **Redis: algo:newgame:stats** | ✓(新游戏) | | | | |
| **Redis: algo:rec:cache** | | | | | ✓ |

---

## 五、数据更新频率汇总

### 5.1 实时更新（秒级）

| 数据 | 触发条件 | 更新方式 |
|------|----------|----------|
| Redis: algo:user:realtime | 用户任意行为 | 行为服务直接写入 |
| Redis: algo:user:behavior_seq | 用户行为 | 行为服务 LPUSH |
| Redis: algo:newgame:stats | 新游戏曝光/点击 | 行为服务 HINCRBY |
| MySQL: algo_recommendation_log | 推荐请求 | 推荐服务异步写入 |

### 5.2 近实时更新（分钟~小时级）

| 数据 | 更新频率 | 更新方式 |
|------|----------|----------|
| Redis: algo:hot:global | 5分钟 | 定时任务聚合 |
| Redis: algo:hot:category:* | 1小时 | 定时任务聚合 |
| MySQL: algo_game_features.hot_score_* | 1小时 | 定时任务更新 |
| MySQL: algo_game_features.play_count_* | 1小时 | 定时任务更新 |

### 5.3 离线更新（T+1）

| 数据 | 更新时间 | 更新方式 |
|------|----------|----------|
| MySQL: algo_user_features | 每日凌晨 | Spark/Hive ETL |
| MySQL: algo_game_features (非热度字段) | 每日凌晨 | Spark/Hive ETL |
| MySQL: algo_game_similarity | 每日凌晨 | Item-CF 离线计算 |
| MySQL: algo_user_recall | 每日凌晨 | 离线召回预计算 |
| Redis: algo:game:similar:* | 每日凌晨 | 从 MySQL 同步 |
| Redis: algo:emb:user:* | 每日凌晨 | Embedding 模型产出 |

### 5.4 周期更新（每周）

| 数据 | 更新时间 | 更新方式 |
|------|----------|----------|
| Redis: algo:emb:game:* | 每周 | Embedding 模型重训练 |

---

## 六、索引策略说明

### 6.1 MySQL 索引设计原则

| 原则 | 说明 |
|------|------|
| **主键查询优先** | 用户特征、游戏特征表以主键查询为主，无需额外索引 |
| **覆盖索引** | 召回查询尽量使用覆盖索引，避免回表 |
| **排序字段在索引末尾** | 如 `(category_id, status, hot_score_7d DESC)` |
| **分区裁剪** | 日志表按日期分区，查询时带上日期条件 |

### 6.2 Redis 访问模式

| 数据结构 | 访问模式 | 时间复杂度 |
|----------|----------|------------|
| Hash | HGETALL / HMGET | O(N) / O(K) |
| List | LRANGE 0 49 | O(N) |
| Sorted Set | ZREVRANGE 0 29 | O(log(N)+M) |
| String | GET | O(1) |

---

## 七、给大数据工程师的 ETL 清单

### 7.1 每日 T+1 任务

| 任务 | 输入 | 输出 | 优先级 |
|------|------|------|--------|
| 用户特征计算 | 用户表 + 行为表 | algo_user_features | P0 |
| 游戏特征计算 | 游戏表 + 行为表 | algo_game_features | P0 |
| Item-CF 相似度计算 | 行为表 | algo_game_similarity | P0 |
| 用户召回预计算 | 相似度 + 用户行为 | algo_user_recall | P1 |
| 用户 Embedding 更新 | 行为表 | Redis algo:emb:user:* | P1 |
| 游戏相似度同步 | algo_game_similarity | Redis algo:game:similar:* | P0 |

### 7.2 小时级任务

| 任务 | 输入 | 输出 | 优先级 |
|------|------|------|--------|
| 热门榜单更新 | 行为表 | Redis algo:hot:* | P0 |
| 游戏热度更新 | 行为表 | algo_game_features.hot_score_* | P0 |

### 7.3 实时任务

| 任务 | 触发 | 输出 | 优先级 |
|------|------|------|--------|
| 用户实时特征更新 | 用户行为事件 | Redis algo:user:realtime:* | P0 |
| 用户行为序列追加 | 用户行为事件 | Redis algo:user:behavior_seq:* | P0 |
| 新游戏统计更新 | 曝光/点击事件 | Redis algo:newgame:stats:* | P1 |

---

## 八、附录

### 8.1 编码映射表（需大数据工程师维护）

| 编码类型 | 说明 | 示例 |
|----------|------|------|
| category_id | 游戏类目 | 1-slots, 2-crash, 3-live, 4-virtual |
| provider_id | 游戏提供商 | 1-pragmatic, 2-evolution, ... |
| theme_id | 游戏主题 | 1-egypt, 2-fruit, 3-asian, ... |
| feature_id | 游戏特性 | 1-megaways, 2-free_spins, 3-bonus_buy, ... |
| channel_id | 注册渠道 | 1-organic, 2-facebook, 3-google, ... |

### 8.2 特征版本管理

- 每次特征逻辑变更需更新 `feature_version` 字段
- A/B测试时可通过版本区分不同特征计算逻辑
- 版本格式：`v{major}.{minor}`，如 `v1.0`, `v1.1`, `v2.0`

