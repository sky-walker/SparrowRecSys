# 游戏推荐系统数据库设计方案

## 一、设计原则

### 1.1 核心设计思想

| 原则 | 说明 |
|------|------|
| **读写分离** | 高频读取使用 Redis 缓存，低频更新存 MySQL |
| **冷热分离** | 实时特征存 Redis，历史特征存 MySQL |
| **宽表设计** | 用户/游戏表采用宽表减少 JOIN 查询 |
| **特征预计算** | 离线计算统计特征，在线直接读取 |
| **可扩展性** | 使用 JSON 字段存储可扩展属性 |

### 1.2 存储职责划分

```
┌─────────────────────────────────────────────────────────────────────┐
│                         数据存储架构                                  │
├─────────────────────────────────────────────────────────────────────┤
│  MySQL (业务数据 + 离线特征)                                         │
│  ├── 用户主表 (users)                                                │
│  ├── 用户画像表 (user_profiles)                                      │
│  ├── 游戏主表 (games)                                                │
│  ├── 游戏提供商表 (game_providers)                                   │
│  ├── 游戏类目表 (game_categories)                                    │
│  ├── 游戏标签表 (game_tags)                                          │
│  ├── 用户行为表 (user_behaviors) - 分区表                            │
│  ├── 用户收藏表 (user_favorites)                                     │
│  ├── 推荐日志表 (recommendation_logs) - 分区表                       │
│  └── 召回结果表 (recall_items) - 离线预计算                          │
├─────────────────────────────────────────────────────────────────────┤
│  Redis (缓存 + 实时特征)                                             │
│  ├── 用户实时特征 (Hash)                                             │
│  ├── 用户行为序列 (List)                                             │
│  ├── 游戏相似矩阵 (Hash)                                             │
│  ├── 热门游戏榜单 (Sorted Set)                                       │
│  ├── 用户/游戏 Embedding (String)                                    │
│  └── 推荐结果缓存 (String)                                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、MySQL 表结构设计

### 2.1 用户主表 (users)

**设计理由：** 存储用户基础账户信息，与业务系统对接。画像信息单独存储以便独立更新。

```sql
CREATE TABLE users (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL COMMENT '用户唯一标识（业务ID）',
    
    -- 基础信息
    username VARCHAR(128) DEFAULT NULL COMMENT '用户名',
    email VARCHAR(256) DEFAULT NULL COMMENT '邮箱',
    phone VARCHAR(32) DEFAULT NULL COMMENT '手机号',
    avatar_url VARCHAR(512) DEFAULT NULL COMMENT '头像URL',
    
    -- 注册信息
    register_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    register_channel VARCHAR(64) DEFAULT NULL COMMENT '注册渠道: organic/facebook_ads/google_ads/affiliate',
    register_device VARCHAR(32) DEFAULT NULL COMMENT '注册设备: ios/android/web',
    register_country VARCHAR(8) DEFAULT NULL COMMENT '注册国家代码 ISO 3166-1',
    register_ip VARCHAR(45) DEFAULT NULL COMMENT '注册IP',
    
    -- 账户状态
    status TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '状态: 0-禁用 1-正常 2-VIP',
    vip_level TINYINT UNSIGNED DEFAULT 0 COMMENT 'VIP等级: 0-9',
    
    -- 最后活跃
    last_login_time DATETIME DEFAULT NULL COMMENT '最后登录时间',
    last_active_time DATETIME DEFAULT NULL COMMENT '最后活跃时间',
    
    -- 时间戳
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 唯一索引
    UNIQUE KEY uk_user_id (user_id),
    
    -- 查询索引
    KEY idx_register_time (register_time),
    KEY idx_register_channel (register_channel),
    KEY idx_last_active_time (last_active_time),
    KEY idx_status_vip (status, vip_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='用户主表';
```

### 2.2 用户画像表 (user_profiles)

**设计理由：** 
- 独立存储用户画像，支持T+1离线更新而不影响主表
- 使用JSON字段存储偏好分布，便于动态扩展
- 预计算统计特征，减少在线计算开销

```sql
CREATE TABLE user_profiles (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL COMMENT '用户唯一标识',
    
    -- 生命周期阶段
    lifecycle_stage ENUM('new', 'growth', 'active', 'mature', 'decline', 'churn') 
        NOT NULL DEFAULT 'new' COMMENT '用户生命周期阶段',
    behavior_count INT UNSIGNED DEFAULT 0 COMMENT '总行为数（用于判断冷启动）',
    active_days_7d TINYINT UNSIGNED DEFAULT 0 COMMENT '近7天活跃天数',
    active_days_30d TINYINT UNSIGNED DEFAULT 0 COMMENT '近30天活跃天数',
    is_churn_risk TINYINT(1) DEFAULT 0 COMMENT '是否流失风险用户',
    
    -- 类目偏好 (权重分布，归一化后的概率)
    -- 示例: {"slots": 0.5, "crash": 0.3, "live": 0.15, "virtual": 0.05}
    preferred_categories JSON DEFAULT NULL COMMENT '类目偏好分布',
    
    -- 提供商偏好
    -- 示例: {"pragmatic_play": 0.4, "spribe": 0.3, "evolution": 0.3}
    preferred_providers JSON DEFAULT NULL COMMENT '提供商偏好分布',
    
    -- 风险偏好（基于游戏波动性选择计算）
    risk_preference ENUM('low', 'medium', 'high') DEFAULT 'medium' COMMENT '风险偏好',
    risk_score DECIMAL(5,4) DEFAULT 0.5000 COMMENT '风险偏好分数 0-1',
    
    -- 主题偏好
    -- 示例: ["mythology", "animal", "asian", "adventure"]
    preferred_themes JSON DEFAULT NULL COMMENT '偏好主题列表',
    
    -- 特性偏好
    -- 示例: {"megaways": 0.3, "free_spins": 0.4, "bonus_buy": 0.3}
    preferred_features JSON DEFAULT NULL COMMENT '游戏特性偏好',
    
    -- 投注模式
    bet_pattern ENUM('small_frequent', 'large_rare', 'mixed') DEFAULT 'mixed' COMMENT '投注模式',
    avg_bet_amount DECIMAL(15,2) DEFAULT 0.00 COMMENT '平均单次投注金额',
    avg_session_duration INT UNSIGNED DEFAULT 0 COMMENT '平均会话时长(秒)',
    
    -- 行为统计
    total_play_count INT UNSIGNED DEFAULT 0 COMMENT '总游戏次数',
    total_play_duration BIGINT UNSIGNED DEFAULT 0 COMMENT '总游戏时长(秒)',
    total_bet_amount DECIMAL(18,2) DEFAULT 0.00 COMMENT '总投注金额',
    total_win_amount DECIMAL(18,2) DEFAULT 0.00 COMMENT '总赢取金额',
    total_favorite_count INT UNSIGNED DEFAULT 0 COMMENT '收藏游戏数',
    
    -- 类目级统计 (用于交叉特征计算)
    -- 示例: {"slots": {"play_count": 100, "ctr": 0.15, "duration": 3600}}
    category_stats JSON DEFAULT NULL COMMENT '类目级统计信息',
    
    -- 提供商级统计
    provider_stats JSON DEFAULT NULL COMMENT '提供商级统计信息',
    
    -- Embedding向量 (用于双塔召回)
    user_embedding BLOB DEFAULT NULL COMMENT '用户Embedding向量(64维float32)',
    embedding_version VARCHAR(32) DEFAULT NULL COMMENT 'Embedding模型版本',
    embedding_updated_at DATETIME DEFAULT NULL COMMENT 'Embedding更新时间',
    
    -- 时间戳
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- 唯一索引
    UNIQUE KEY uk_user_id (user_id),
    
    -- 查询索引
    KEY idx_lifecycle (lifecycle_stage),
    KEY idx_churn_risk (is_churn_risk),
    KEY idx_risk_preference (risk_preference),
    KEY idx_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='用户画像表';

### 2.3 游戏类目表 (game_categories)

**设计理由：** 类目作为独立维度表，支持多级类目和灵活扩展。

```sql
CREATE TABLE game_categories (
    -- 主键
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    -- 类目信息
    category_code VARCHAR(32) NOT NULL COMMENT '类目编码: slots/crash/live/virtual',
    category_name VARCHAR(64) NOT NULL COMMENT '类目名称',
    parent_id INT UNSIGNED DEFAULT NULL COMMENT '父类目ID（支持多级类目）',
    level TINYINT UNSIGNED DEFAULT 1 COMMENT '类目层级: 1-一级 2-二级',

    -- 显示属性
    icon_url VARCHAR(256) DEFAULT NULL COMMENT '图标URL',
    sort_order INT UNSIGNED DEFAULT 0 COMMENT '排序权重',
    is_visible TINYINT(1) DEFAULT 1 COMMENT '是否可见',

    -- 统计缓存
    game_count INT UNSIGNED DEFAULT 0 COMMENT '游戏数量',

    -- 时间戳
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 唯一索引
    UNIQUE KEY uk_category_code (category_code),

    -- 查询索引
    KEY idx_parent_id (parent_id),
    KEY idx_sort_order (sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏类目表';

-- 初始化基础类目
INSERT INTO game_categories (category_code, category_name, level, sort_order) VALUES
('slots', 'Slots', 1, 1),
('crash', 'Crash Games', 1, 2),
('live', 'Live Casino', 1, 3),
('virtual', 'Virtual Sports', 1, 4),
('table', 'Table Games', 1, 5);
```

### 2.4 游戏提供商表 (game_providers)

**设计理由：** 游戏提供商是重要的内容召回维度，单独维护便于管理和统计。

```sql
CREATE TABLE game_providers (
    -- 主键
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    -- 提供商信息
    provider_code VARCHAR(64) NOT NULL COMMENT '提供商编码',
    provider_name VARCHAR(128) NOT NULL COMMENT '提供商名称',
    logo_url VARCHAR(256) DEFAULT NULL COMMENT 'Logo URL',

    -- 属性
    is_premium TINYINT(1) DEFAULT 0 COMMENT '是否优质提供商',
    avg_rtp DECIMAL(5,2) DEFAULT NULL COMMENT '平均RTP',

    -- 统计缓存
    game_count INT UNSIGNED DEFAULT 0 COMMENT '游戏数量',
    total_play_count_7d BIGINT UNSIGNED DEFAULT 0 COMMENT '7天总游戏次数',

    -- 状态
    status TINYINT(1) DEFAULT 1 COMMENT '状态: 0-禁用 1-启用',

    -- 时间戳
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 唯一索引
    UNIQUE KEY uk_provider_code (provider_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏提供商表';

-- 初始化示例提供商
INSERT INTO game_providers (provider_code, provider_name, is_premium) VALUES
('pragmatic_play', 'Pragmatic Play', 1),
('spribe', 'Spribe', 1),
('evolution', 'Evolution Gaming', 1),
('netent', 'NetEnt', 1),
('microgaming', 'Microgaming', 0);
```

### 2.5 游戏主表 (games)

**设计理由：**
- 宽表设计，包含所有游戏属性和统计特征
- 预计算热度指标，支持热门召回
- 存储Embedding向量，支持向量召回
- JSON字段存储多值属性（themes/features）

```sql
CREATE TABLE games (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    game_id VARCHAR(64) NOT NULL COMMENT '游戏唯一标识',

    -- 基础信息
    game_name VARCHAR(128) NOT NULL COMMENT '游戏名称',
    game_name_en VARCHAR(128) DEFAULT NULL COMMENT '英文名称',
    description TEXT DEFAULT NULL COMMENT '游戏描述',
    thumbnail_url VARCHAR(512) DEFAULT NULL COMMENT '缩略图URL',
    banner_url VARCHAR(512) DEFAULT NULL COMMENT '横幅图URL',
    game_url VARCHAR(512) DEFAULT NULL COMMENT '游戏启动URL',

    -- 分类信息（外键关联）
    category_id INT UNSIGNED NOT NULL COMMENT '类目ID',
    sub_category VARCHAR(32) DEFAULT NULL COMMENT '子类目: megaways/classic/aviator等',
    provider_id INT UNSIGNED NOT NULL COMMENT '提供商ID',

    -- 游戏核心属性
    rtp DECIMAL(5,2) DEFAULT NULL COMMENT '理论返还率 (如96.50)',
    rtp_range_min DECIMAL(5,2) DEFAULT NULL COMMENT 'RTP最小值（部分游戏有范围）',
    rtp_range_max DECIMAL(5,2) DEFAULT NULL COMMENT 'RTP最大值',
    volatility ENUM('low', 'medium', 'high', 'very_high') DEFAULT 'medium' COMMENT '波动性',
    volatility_score DECIMAL(3,2) DEFAULT NULL COMMENT '波动性数值 1.00-5.00',
    hit_frequency DECIMAL(5,2) DEFAULT NULL COMMENT '命中频率百分比',
    max_win_multiplier INT UNSIGNED DEFAULT NULL COMMENT '最大赢取倍数 (如5000x)',

    -- 投注范围
    min_bet DECIMAL(10,2) DEFAULT 0.01 COMMENT '最小投注金额',
    max_bet DECIMAL(10,2) DEFAULT 1000.00 COMMENT '最大投注金额',

    -- 多值属性（JSON）
    -- 示例: ["mythology", "greek", "zeus"]
    themes JSON DEFAULT NULL COMMENT '游戏主题标签',
    -- 示例: ["megaways", "free_spins", "bonus_buy", "multiplier"]
    features JSON DEFAULT NULL COMMENT '游戏特性标签',
    -- 示例: {"lines": 20, "reels": 5, "rows": 3}
    technical_info JSON DEFAULT NULL COMMENT '技术参数',

    -- 状态信息
    status TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '状态: 0-下线 1-上线 2-维护',
    launch_date DATE DEFAULT NULL COMMENT '上线日期',
    lifecycle_stage ENUM('new', 'growth', 'mature', 'decline') DEFAULT 'new' COMMENT '游戏生命周期',

    -- 运营属性
    is_featured TINYINT(1) DEFAULT 0 COMMENT '是否推荐位',
    is_new TINYINT(1) DEFAULT 0 COMMENT '是否新游戏（7天内）',
    is_hot TINYINT(1) DEFAULT 0 COMMENT '是否热门',
    is_jackpot TINYINT(1) DEFAULT 0 COMMENT '是否有累积奖池',
    boost_weight DECIMAL(3,2) DEFAULT 1.00 COMMENT '运营加权 0.50-2.00',

    -- 热度统计（定期更新）
    play_count_1h INT UNSIGNED DEFAULT 0 COMMENT '1小时游戏次数',
    play_count_24h INT UNSIGNED DEFAULT 0 COMMENT '24小时游戏次数',
    play_count_7d INT UNSIGNED DEFAULT 0 COMMENT '7天游戏次数',
    play_count_30d INT UNSIGNED DEFAULT 0 COMMENT '30天游戏次数',
    unique_players_7d INT UNSIGNED DEFAULT 0 COMMENT '7天独立玩家数',
    unique_players_30d INT UNSIGNED DEFAULT 0 COMMENT '30天独立玩家数',

    -- 效果指标
    impression_count_7d INT UNSIGNED DEFAULT 0 COMMENT '7天曝光次数',
    click_count_7d INT UNSIGNED DEFAULT 0 COMMENT '7天点击次数',
    ctr_7d DECIMAL(6,4) DEFAULT 0.0000 COMMENT '7天点击率',
    cvr_7d DECIMAL(6,4) DEFAULT 0.0000 COMMENT '7天转化率(点击到游戏)',
    avg_session_duration INT UNSIGNED DEFAULT 0 COMMENT '平均游戏时长(秒)',
    avg_bet_amount DECIMAL(15,2) DEFAULT 0.00 COMMENT '平均单次投注',

    -- 评分
    avg_rating DECIMAL(3,2) DEFAULT 0.00 COMMENT '平均评分 0-5',
    rating_count INT UNSIGNED DEFAULT 0 COMMENT '评分人数',
    favorite_count INT UNSIGNED DEFAULT 0 COMMENT '收藏数',

    -- Embedding向量（用于向量召回）
    game_embedding BLOB DEFAULT NULL COMMENT '游戏Embedding向量(64维float32)',
    embedding_version VARCHAR(32) DEFAULT NULL COMMENT 'Embedding模型版本',
    embedding_updated_at DATETIME DEFAULT NULL COMMENT 'Embedding更新时间',

    -- 时间戳
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 唯一索引
    UNIQUE KEY uk_game_id (game_id),

    -- 外键索引
    KEY idx_category_id (category_id),
    KEY idx_provider_id (provider_id),

    -- 查询索引
    KEY idx_category_status (category_id, status),
    KEY idx_provider_status (provider_id, status),
    KEY idx_launch_date (launch_date),
    KEY idx_lifecycle (lifecycle_stage),
    KEY idx_volatility (volatility),
    KEY idx_rtp (rtp),

    -- 热门召回索引
    KEY idx_hot_1h (status, play_count_1h DESC),
    KEY idx_hot_24h (status, play_count_24h DESC),
    KEY idx_hot_7d (status, play_count_7d DESC),
    KEY idx_category_hot (category_id, status, play_count_7d DESC),
    KEY idx_provider_hot (provider_id, status, play_count_7d DESC),

    -- 新游戏召回索引
    KEY idx_new_games (is_new, launch_date DESC),

    -- 推荐位索引
    KEY idx_featured (is_featured, boost_weight DESC),

    -- 全文索引（搜索用）
    FULLTEXT KEY ft_game_name (game_name, game_name_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏主表';

### 2.6 游戏标签表 (game_tags)

**设计理由：** 标签单独存储，支持多对多关系，便于标签管理和基于标签的内容召回。

```sql
CREATE TABLE game_tags (
    -- 主键
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    -- 标签信息
    tag_code VARCHAR(64) NOT NULL COMMENT '标签编码',
    tag_name VARCHAR(64) NOT NULL COMMENT '标签名称',
    tag_type ENUM('theme', 'feature', 'mechanic', 'style') NOT NULL COMMENT '标签类型',

    -- 属性
    description VARCHAR(256) DEFAULT NULL COMMENT '标签描述',
    icon_url VARCHAR(256) DEFAULT NULL COMMENT '图标URL',

    -- 统计
    game_count INT UNSIGNED DEFAULT 0 COMMENT '关联游戏数',

    -- 时间戳
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 唯一索引
    UNIQUE KEY uk_tag_code (tag_code),

    -- 查询索引
    KEY idx_tag_type (tag_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏标签表';

-- 游戏-标签关联表
CREATE TABLE game_tag_relations (
    game_id VARCHAR(64) NOT NULL COMMENT '游戏ID',
    tag_id INT UNSIGNED NOT NULL COMMENT '标签ID',
    weight DECIMAL(3,2) DEFAULT 1.00 COMMENT '标签权重',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (game_id, tag_id),
    KEY idx_tag_id (tag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏-标签关联表';

-- 初始化示例标签
INSERT INTO game_tags (tag_code, tag_name, tag_type) VALUES
-- 主题标签
('mythology', 'Mythology', 'theme'),
('greek', 'Greek', 'theme'),
('egyptian', 'Egyptian', 'theme'),
('asian', 'Asian', 'theme'),
('animal', 'Animal', 'theme'),
('adventure', 'Adventure', 'theme'),
('fantasy', 'Fantasy', 'theme'),
('fruits', 'Fruits', 'theme'),
-- 特性标签
('megaways', 'Megaways', 'feature'),
('free_spins', 'Free Spins', 'feature'),
('bonus_buy', 'Bonus Buy', 'feature'),
('multiplier', 'Multiplier', 'feature'),
('cascading', 'Cascading', 'feature'),
('expanding_wilds', 'Expanding Wilds', 'feature'),
-- 玩法标签
('instant_win', 'Instant Win', 'mechanic'),
('skill_based', 'Skill Based', 'mechanic');
```

### 2.7 用户行为表 (user_behaviors)

**设计理由：**
- 按月分区，支持历史数据归档
- 包含完整的行为上下文（设备、会话等）
- 预留扩展字段存储特殊行为数据

```sql
CREATE TABLE user_behaviors (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT,

    -- 核心字段
    user_id VARCHAR(64) NOT NULL COMMENT '用户ID',
    game_id VARCHAR(64) NOT NULL COMMENT '游戏ID',
    behavior_type ENUM('impression', 'click', 'play', 'bet', 'win', 'favorite', 'unfavorite', 'share', 'rate')
        NOT NULL COMMENT '行为类型',

    -- 行为详情
    duration INT UNSIGNED DEFAULT 0 COMMENT '行为时长(秒)',
    bet_amount DECIMAL(15,2) DEFAULT NULL COMMENT '投注金额',
    win_amount DECIMAL(15,2) DEFAULT NULL COMMENT '赢取金额',
    rating_score DECIMAL(2,1) DEFAULT NULL COMMENT '评分 1.0-5.0',

    -- 上下文信息
    session_id VARCHAR(64) DEFAULT NULL COMMENT '会话ID',
    device_type VARCHAR(16) DEFAULT NULL COMMENT '设备类型: ios/android/web',
    platform VARCHAR(32) DEFAULT NULL COMMENT '平台来源',
    scene VARCHAR(32) DEFAULT NULL COMMENT '场景: home/category/search/similar',
    position INT UNSIGNED DEFAULT NULL COMMENT '展示位置',

    -- 推荐来源追踪
    request_id VARCHAR(64) DEFAULT NULL COMMENT '推荐请求ID',
    recall_source VARCHAR(32) DEFAULT NULL COMMENT '召回来源: hot/itemcf/embedding/content',

    -- 扩展字段
    extra_data JSON DEFAULT NULL COMMENT '扩展数据',

    -- 时间
    behavior_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '行为时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 主键（包含分区键）
    PRIMARY KEY (id, behavior_time),

    -- 查询索引
    KEY idx_user_time (user_id, behavior_time),
    KEY idx_game_time (game_id, behavior_time),
    KEY idx_user_game (user_id, game_id, behavior_type),
    KEY idx_behavior_type_time (behavior_type, behavior_time),
    KEY idx_session (session_id),
    KEY idx_request (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='用户行为表'
PARTITION BY RANGE (TO_DAYS(behavior_time)) (
    PARTITION p202601 VALUES LESS THAN (TO_DAYS('2026-02-01')),
    PARTITION p202602 VALUES LESS THAN (TO_DAYS('2026-03-01')),
    PARTITION p202603 VALUES LESS THAN (TO_DAYS('2026-04-01')),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);
```

### 2.8 用户收藏表 (user_favorites)

**设计理由：** 收藏是重要的显式反馈，单独存储支持个性化召回。

```sql
CREATE TABLE user_favorites (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    -- 核心字段
    user_id VARCHAR(64) NOT NULL COMMENT '用户ID',
    game_id VARCHAR(64) NOT NULL COMMENT '游戏ID',

    -- 状态
    is_active TINYINT(1) DEFAULT 1 COMMENT '是否有效（支持取消收藏）',

    -- 时间
    favorited_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
    unfavorited_at DATETIME DEFAULT NULL COMMENT '取消收藏时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 唯一索引
    UNIQUE KEY uk_user_game (user_id, game_id),

    -- 查询索引
    KEY idx_user_active (user_id, is_active),
    KEY idx_game_id (game_id),
    KEY idx_favorited_at (favorited_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='用户收藏表';

### 2.9 游戏相似度表 (game_similarities)

**设计理由：**
- 离线预计算的Item-CF相似度矩阵
- 支持分类内和跨类召回
- 定期更新，Redis同步缓存

```sql
CREATE TABLE game_similarities (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    -- 核心字段
    game_id VARCHAR(64) NOT NULL COMMENT '源游戏ID',
    similar_game_id VARCHAR(64) NOT NULL COMMENT '相似游戏ID',

    -- 相似度
    similarity_score DECIMAL(6,5) NOT NULL COMMENT '相似度分数 0-1',
    similarity_type ENUM('itemcf', 'content', 'embedding') DEFAULT 'itemcf' COMMENT '相似度类型',

    -- 排序
    rank_position SMALLINT UNSIGNED DEFAULT NULL COMMENT '相似度排名',

    -- 版本控制
    version VARCHAR(32) DEFAULT NULL COMMENT '计算版本',

    -- 时间
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- 唯一索引（每种类型的相似对唯一）
    UNIQUE KEY uk_game_similar_type (game_id, similar_game_id, similarity_type),

    -- 查询索引
    KEY idx_game_type_rank (game_id, similarity_type, rank_position),
    KEY idx_similar_game (similar_game_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='游戏相似度表';
```

### 2.10 召回预计算表 (recall_candidates)

**设计理由：**
- 离线预计算用户召回候选集
- 按召回策略分别存储
- 支持快速在线查询

```sql
CREATE TABLE recall_candidates (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    -- 核心字段
    user_id VARCHAR(64) NOT NULL COMMENT '用户ID',
    game_id VARCHAR(64) NOT NULL COMMENT '游戏ID',

    -- 召回信息
    recall_type ENUM('itemcf', 'embedding', 'content', 'hot', 'new', 'personal')
        NOT NULL COMMENT '召回类型',
    recall_score DECIMAL(8,6) NOT NULL COMMENT '召回分数',
    recall_reason VARCHAR(128) DEFAULT NULL COMMENT '召回原因描述',

    -- 排序
    rank_position SMALLINT UNSIGNED DEFAULT NULL COMMENT '排名位置',

    -- 版本控制
    version VARCHAR(32) DEFAULT NULL COMMENT '计算版本',
    expire_at DATETIME DEFAULT NULL COMMENT '过期时间',

    -- 时间
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 唯一索引
    UNIQUE KEY uk_user_game_type (user_id, game_id, recall_type),

    -- 查询索引
    KEY idx_user_type_rank (user_id, recall_type, rank_position),
    KEY idx_expire (expire_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='召回预计算表';
```

### 2.11 推荐日志表 (recommendation_logs)

**设计理由：**
- 记录完整推荐链路，用于效果评估和A/B测试
- 按日分区，支持快速清理
- 包含各阶段耗时，用于性能分析

```sql
CREATE TABLE recommendation_logs (
    -- 主键
    id BIGINT UNSIGNED AUTO_INCREMENT,

    -- 请求标识
    request_id VARCHAR(64) NOT NULL COMMENT '请求唯一ID',
    user_id VARCHAR(64) NOT NULL COMMENT '用户ID',

    -- 请求上下文
    scene VARCHAR(32) NOT NULL COMMENT '推荐场景: home/category/similar',
    device_type VARCHAR(16) DEFAULT NULL COMMENT '设备类型',
    platform VARCHAR(32) DEFAULT NULL COMMENT '平台',

    -- A/B测试
    experiment_id VARCHAR(64) DEFAULT NULL COMMENT '实验ID',
    experiment_group VARCHAR(32) DEFAULT NULL COMMENT '实验分组',

    -- 推荐结果
    recalled_games JSON DEFAULT NULL COMMENT '召回游戏列表',
    recalled_count INT UNSIGNED DEFAULT 0 COMMENT '召回数量',
    ranked_games JSON DEFAULT NULL COMMENT '精排后游戏列表',
    final_games JSON DEFAULT NULL COMMENT '最终推荐游戏列表',
    final_count INT UNSIGNED DEFAULT 0 COMMENT '最终推荐数量',

    -- 各阶段召回源统计
    recall_stats JSON DEFAULT NULL COMMENT '各路召回统计',

    -- 性能指标
    recall_latency_ms INT UNSIGNED DEFAULT 0 COMMENT '召回耗时(ms)',
    rank_latency_ms INT UNSIGNED DEFAULT 0 COMMENT '精排耗时(ms)',
    rerank_latency_ms INT UNSIGNED DEFAULT 0 COMMENT '重排耗时(ms)',
    total_latency_ms INT UNSIGNED DEFAULT 0 COMMENT '总耗时(ms)',

    -- 用户反馈（后续回填）
    clicked_games JSON DEFAULT NULL COMMENT '点击的游戏',
    played_games JSON DEFAULT NULL COMMENT '开始游戏的游戏',
    ctr DECIMAL(5,4) DEFAULT NULL COMMENT '点击率',
    cvr DECIMAL(5,4) DEFAULT NULL COMMENT '转化率',

    -- 时间
    request_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '请求时间',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 主键
    PRIMARY KEY (id, request_time),

    -- 索引
    UNIQUE KEY uk_request_id (request_id, request_time),
    KEY idx_user_time (user_id, request_time),
    KEY idx_scene_time (scene, request_time),
    KEY idx_experiment (experiment_id, experiment_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='推荐日志表'
PARTITION BY RANGE (TO_DAYS(request_time)) (
    PARTITION p20260101 VALUES LESS THAN (TO_DAYS('2026-01-02')),
    PARTITION p20260102 VALUES LESS THAN (TO_DAYS('2026-01-03')),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);
```

---

## 三、Redis 数据结构设计

### 3.1 用户实时特征 (Hash)

**用途：** 存储用户Session级别的实时特征，用于在线精排。

```
Key: user:realtime:{user_id}
Type: Hash
TTL: 30分钟（无活动自动过期）

Fields:
  - session_id: 当前会话ID
  - session_start: 会话开始时间戳
  - viewed_games: JSON数组 ["game1", "game2", ...]（本次会话已浏览）
  - clicked_games: JSON数组（本次会话已点击）
  - played_games: JSON数组（本次会话已游戏）
  - last_action_time: 最后一次行为时间戳
  - last_action_type: 最后一次行为类型
  - current_balance_tier: 当前余额区间 low/medium/high
  - device_type: 设备类型
  - geo_country: 地理位置
```

```python
# 示例操作
redis.hset("user:realtime:u123", mapping={
    "session_id": "sess_abc123",
    "session_start": "1737216000",
    "viewed_games": '["game1", "game2"]',
    "clicked_games": '["game1"]',
    "played_games": '[]',
    "last_action_time": "1737216300",
    "last_action_type": "click",
    "device_type": "ios"
})
redis.expire("user:realtime:u123", 1800)  # 30分钟过期
```

### 3.2 用户行为序列 (List)

**用途：** 存储用户近期行为序列，用于DIN模型和Item-CF召回。

```
Key: user:behavior_seq:{user_id}
Type: List
TTL: 7天
Max Length: 100（使用LTRIM保持长度）

Value: JSON格式的行为记录
```

```python
# 示例操作 - 添加行为
behavior = {
    "game_id": "gate_of_olympus",
    "type": "play",
    "duration": 300,
    "timestamp": 1737216000
}
redis.lpush(f"user:behavior_seq:{user_id}", json.dumps(behavior))
redis.ltrim(f"user:behavior_seq:{user_id}", 0, 99)  # 保留最近100条
redis.expire(f"user:behavior_seq:{user_id}", 604800)  # 7天过期
```

### 3.3 热门游戏榜单 (Sorted Set)

**用途：** 多维度热门榜单，支持热门召回。

```
Key Pattern:
  - game:hot:realtime       # 实时热门（1小时内）
  - game:hot:daily          # 日热门
  - game:hot:weekly         # 周热门
  - game:hot:category:{category}  # 分类热门
  - game:hot:provider:{provider}  # 提供商热门
  - game:hot:period:{period}      # 时段热门 morning/afternoon/evening/night

Type: Sorted Set
Score: 热度分数（可以是播放次数、加权分数等）
Member: game_id
```

```python
# 示例操作 - 更新热门榜
redis.zadd("game:hot:realtime", {"gate_of_olympus": 1500, "aviator": 1200})
redis.zadd("game:hot:category:slots", {"gate_of_olympus": 1500, "sweet_bonanza": 1100})

# 获取热门
hot_games = redis.zrevrange("game:hot:realtime", 0, 19, withscores=True)
```

### 3.4 游戏相似矩阵 (Hash)

**用途：** 存储Item-CF预计算的相似游戏，支持快速相似召回。

```
Key: game:similar:{game_id}
Type: Hash
TTL: 1天（每日更新）

Field: similar_game_id
Value: similarity_score (float string)
```

```python
# 示例操作 - 写入相似矩阵
redis.hset("game:similar:gate_of_olympus", mapping={
    "sweet_bonanza": "0.85",
    "starlight_princess": "0.78",
    "gates_of_olympus_1000": "0.92"
})
redis.expire("game:similar:gate_of_olympus", 86400)

# 获取相似游戏
similar = redis.hgetall("game:similar:gate_of_olympus")
```

### 3.5 Embedding向量 (String)

**用途：** 存储用户和游戏的Embedding向量，支持向量召回。

```
Key Pattern:
  - user:emb:{user_id}    # 用户Embedding
  - game:emb:{game_id}    # 游戏Embedding

Type: String (二进制存储 64维 float32 = 256 bytes)
TTL: 用户Embedding 1天，游戏Embedding 7天
```

```python
import numpy as np

# 示例操作 - 存储Embedding
user_emb = np.random.randn(64).astype(np.float32)
redis.set(f"user:emb:{user_id}", user_emb.tobytes(), ex=86400)

# 读取Embedding
emb_bytes = redis.get(f"user:emb:{user_id}")
if emb_bytes:
    user_emb = np.frombuffer(emb_bytes, dtype=np.float32)
```

### 3.6 推荐结果缓存 (String)

**用途：** 缓存用户推荐结果，避免重复计算。

```
Key: rec:cache:{user_id}:{scene}
Type: String (JSON格式)
TTL: 5分钟（首页）/ 10分钟（类目页）
```

```python
# 示例结构
cache_data = {
    "request_id": "req_abc123",
    "games": [
        {"game_id": "gate_of_olympus", "score": 0.95, "source": "hot"},
        {"game_id": "aviator", "score": 0.88, "source": "itemcf"}
    ],
    "generated_at": 1737216000,
    "version": "v1.0"
}
redis.setex(f"rec:cache:{user_id}:home", 300, json.dumps(cache_data))
```

### 3.7 用户最近游戏列表 (List)

**用途：** 存储用户最近玩过的游戏，用于续玩召回和过滤。

```
Key: user:recent_games:{user_id}
Type: List
TTL: 30天
Max Length: 50
```

```python
# 添加最近游戏（去重后添加）
redis.lrem(f"user:recent_games:{user_id}", 0, game_id)  # 先移除旧记录
redis.lpush(f"user:recent_games:{user_id}", game_id)
redis.ltrim(f"user:recent_games:{user_id}", 0, 49)
redis.expire(f"user:recent_games:{user_id}", 2592000)
```

### 3.8 新游戏曝光统计 (Hash)

**用途：** 记录新游戏曝光和点击数据，用于Thompson Sampling。

```
Key: game:newgame_stats:{game_id}
Type: Hash
TTL: 30天

Fields:
  - impression_count: 曝光次数
  - click_count: 点击次数
  - play_count: 游戏次数
  - launch_date: 上线日期
```

```python
# 更新曝光
redis.hincrby(f"game:newgame_stats:{game_id}", "impression_count", 1)

# 计算Thompson Sampling分数
stats = redis.hgetall(f"game:newgame_stats:{game_id}")
alpha = int(stats.get("click_count", 0)) + 1
beta = int(stats.get("impression_count", 0)) - int(stats.get("click_count", 0)) + 1
sampled_ctr = np.random.beta(alpha, beta)
```

### 3.9 Redis 数据结构汇总

| Key Pattern | 类型 | TTL | 用途 |
|-------------|------|-----|------|
| `user:realtime:{user_id}` | Hash | 30分钟 | 用户实时Session特征 |
| `user:behavior_seq:{user_id}` | List | 7天 | 用户行为序列 |
| `user:recent_games:{user_id}` | List | 30天 | 最近玩过的游戏 |
| `user:emb:{user_id}` | String | 1天 | 用户Embedding向量 |
| `game:hot:{dimension}` | Sorted Set | 1小时/1天 | 多维度热门榜单 |
| `game:similar:{game_id}` | Hash | 1天 | 游戏相似矩阵 |
| `game:emb:{game_id}` | String | 7天 | 游戏Embedding向量 |
| `game:newgame_stats:{game_id}` | Hash | 30天 | 新游戏曝光统计 |
| `rec:cache:{user_id}:{scene}` | String | 5-10分钟 | 推荐结果缓存 |

---

## 四、索引策略详解

### 4.1 索引设计原则

| 原则 | 说明 |
|------|------|
| **最左前缀** | 复合索引遵循最左前缀原则 |
| **覆盖索引** | 高频查询尽量使用覆盖索引 |
| **区分度优先** | 高区分度字段放在索引前面 |
| **避免冗余** | 避免重复索引，定期清理 |

### 4.2 核心查询场景索引

#### 用户画像查询
```sql
-- 场景1: 按用户ID查询画像
-- 使用 uk_user_id 唯一索引
SELECT * FROM user_profiles WHERE user_id = 'u123';

-- 场景2: 查询流失风险用户
-- 使用 idx_churn_risk 索引
SELECT * FROM user_profiles WHERE is_churn_risk = 1;

-- 场景3: 查询特定生命周期用户
-- 使用 idx_lifecycle 索引
SELECT * FROM user_profiles WHERE lifecycle_stage = 'new';
```

#### 游戏召回查询
```sql
-- 场景1: 分类热门召回
-- 使用 idx_category_hot (category_id, status, play_count_7d)
SELECT game_id, game_name, play_count_7d
FROM games
WHERE category_id = 1 AND status = 1
ORDER BY play_count_7d DESC
LIMIT 50;

-- 场景2: 新游戏召回
-- 使用 idx_new_games (is_new, launch_date)
SELECT game_id, game_name, launch_date
FROM games
WHERE is_new = 1
ORDER BY launch_date DESC
LIMIT 20;

-- 场景3: 相似游戏召回
-- 使用 idx_game_type_rank
SELECT similar_game_id, similarity_score
FROM game_similarities
WHERE game_id = 'gate_of_olympus' AND similarity_type = 'itemcf'
ORDER BY rank_position
LIMIT 50;
```

#### 用户行为查询
```sql
-- 场景1: 查询用户最近行为（用于特征计算）
-- 使用 idx_user_time (user_id, behavior_time)
SELECT * FROM user_behaviors
WHERE user_id = 'u123'
  AND behavior_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY behavior_time DESC;

-- 场景2: 查询游戏统计（用于热度计算）
-- 使用 idx_game_time (game_id, behavior_time)
SELECT game_id, COUNT(*) as play_count
FROM user_behaviors
WHERE behavior_type = 'play'
  AND behavior_time >= DATE_SUB(NOW(), INTERVAL 1 DAY)
GROUP BY game_id;
```

### 4.3 分区策略

| 表 | 分区方式 | 分区键 | 保留策略 |
|-----|---------|--------|----------|
| user_behaviors | 按月RANGE | behavior_time | 保留12个月 |
| recommendation_logs | 按日RANGE | request_time | 保留30天 |

```sql
-- 自动创建新分区（定时任务）
ALTER TABLE user_behaviors
ADD PARTITION (
    PARTITION p202604 VALUES LESS THAN (TO_DAYS('2026-05-01'))
);

-- 删除旧分区
ALTER TABLE user_behaviors DROP PARTITION p202501;
```

---

## 五、表关系说明

### 5.1 ER 图

```
┌───────────────┐         ┌───────────────┐
│    users      │         │game_categories│
│───────────────│         │───────────────│
│ user_id (PK)  │         │ id (PK)       │
│ username      │         │ category_code │
│ register_time │         │ category_name │
└───────┬───────┘         └───────┬───────┘
        │                         │
        │ 1:1                     │ 1:N
        │                         │
        ▼                         ▼
┌───────────────┐         ┌───────────────┐
│ user_profiles │         │    games      │
│───────────────│         │───────────────│
│ user_id (FK)  │◄────────│ game_id (PK)  │
│ lifecycle_stage│   N:M  │ category_id(FK)│
│ preferred_*   │         │ provider_id(FK)│
└───────┬───────┘         └───────┬───────┘
        │                         │
        │ 1:N                     │ 1:N
        │                         │
        ▼                         ▼
┌───────────────┐         ┌───────────────┐
│user_behaviors │         │game_providers │
│───────────────│         │───────────────│
│ user_id (FK)  │         │ id (PK)       │
│ game_id (FK)  │         │ provider_code │
│ behavior_type │         │ provider_name │
└───────────────┘         └───────────────┘
        │
        │
        ▼
┌───────────────────────────────────────────┐
│           user_favorites                   │
│───────────────────────────────────────────│
│ user_id (FK)  │  game_id (FK)  │ is_active│
└───────────────────────────────────────────┘

        游戏间关系
┌───────────────┐         ┌───────────────┐
│    games      │◄────────│game_similarities│
│───────────────│  1:N    │───────────────│
│ game_id (PK)  │         │ game_id (FK)  │
│               │         │similar_game_id│
│               │         │similarity_score│
└───────────────┘         └───────────────┘

        标签关系
┌───────────────┐         ┌───────────────┐
│    games      │◄────────│game_tag_relations│
│───────────────│   N:M   │───────────────│
│ game_id (PK)  │         │ game_id (FK)  │
│               │         │ tag_id (FK)   │
└───────────────┘         └───────┬───────┘
                                  │
                                  │ N:1
                                  ▼
                          ┌───────────────┐
                          │  game_tags    │
                          │───────────────│
                          │ id (PK)       │
                          │ tag_code      │
                          │ tag_type      │
                          └───────────────┘
```

### 5.2 关系说明

| 关系 | 类型 | 说明 |
|------|------|------|
| users → user_profiles | 1:1 | 用户基础信息与画像分离 |
| users → user_behaviors | 1:N | 用户产生多条行为记录 |
| users → user_favorites | 1:N | 用户可收藏多个游戏 |
| game_categories → games | 1:N | 一个类目包含多个游戏 |
| game_providers → games | 1:N | 一个提供商有多个游戏 |
| games → game_similarities | 1:N | 一个游戏对应多个相似游戏 |
| games ↔ game_tags | N:M | 游戏和标签多对多关系 |
| games → user_behaviors | 1:N | 一个游戏对应多条行为 |

---

## 六、数据更新策略

### 6.1 更新频率

| 数据类型 | 更新频率 | 更新方式 |
|----------|----------|----------|
| 用户画像 | T+1（每日） | 离线Spark任务 |
| 游戏热度统计 | 每小时 | 定时任务 |
| 相似度矩阵 | 每日 | 离线计算 |
| Embedding向量 | 每日/周 | 离线训练 |
| 实时特征 | 实时 | 行为触发更新 |
| 推荐缓存 | 5-10分钟TTL | 自动过期 |

### 6.2 数据同步流程

```
                    用户行为
                        │
                        ▼
    ┌──────────────────────────────────┐
    │          Kafka / 消息队列          │
    │     (行为事件流，异步处理)          │
    └───────────────┬──────────────────┘
                    │
         ┌──────────┴──────────┐
         │                     │
         ▼                     ▼
┌─────────────────┐   ┌─────────────────┐
│   实时处理       │   │   离线处理       │
│   (Celery)      │   │   (Spark)       │
│                 │   │                 │
│ - 更新Redis     │   │ - T+1画像更新   │
│   实时特征       │   │ - 相似度计算    │
│ - 更新行为序列   │   │ - Embedding训练 │
│ - 更新热门榜     │   │ - 统计指标计算   │
└────────┬────────┘   └────────┬────────┘
         │                     │
         ▼                     ▼
┌─────────────────┐   ┌─────────────────┐
│     Redis       │   │     MySQL       │
│  (实时特征)      │   │  (离线特征)     │
└─────────────────┘   └─────────────────┘
```

---

## 七、设计亮点与最佳实践

### 7.1 支持多路召回的设计

| 召回策略 | 数据来源 | 相关表/结构 |
|----------|----------|-------------|
| **热门召回** | Redis Sorted Set | `game:hot:{dimension}` |
| **Item-CF召回** | 预计算相似矩阵 | `game_similarities` + `game:similar:{id}` |
| **Embedding召回** | 向量检索 | `games.game_embedding` + `game:emb:{id}` |
| **内容召回** | 属性匹配 | `games.themes/features` + `user_profiles.preferred_*` |
| **新游戏召回** | 新游戏池 | `games.is_new` + `game:newgame_stats:{id}` |
| **个性化召回** | 续玩+收藏 | `user:recent_games:{id}` + `user_favorites` |

### 7.2 用户画像设计亮点

1. **偏好分布存储**：使用JSON存储概率分布，支持多类目/提供商偏好
2. **风险偏好量化**：将用户波动性偏好转化为可计算的分数
3. **类目级统计**：预计算各类目的CTR/CVR，用于交叉特征
4. **Embedding集成**：直接存储用户向量，支持双塔召回

### 7.3 游戏表设计亮点

1. **多维度热度指标**：1h/24h/7d/30d多时间窗口热度
2. **效果指标预计算**：CTR/CVR/平均时长等核心指标
3. **运营加权支持**：`boost_weight`字段支持运营干预
4. **生命周期管理**：新游戏标识和生命周期阶段追踪

### 7.4 行为表设计亮点

1. **完整上下文**：记录设备、场景、位置等推荐上下文
2. **推荐追踪**：`request_id`和`recall_source`支持归因分析
3. **分区策略**：按月分区支持历史数据管理
4. **扩展字段**：JSON扩展字段应对未来需求

### 7.5 冷启动支持

| 场景 | 设计支持 |
|------|----------|
| **新用户** | `users.register_channel/device` 提供Side Information |
| **新游戏** | `game:newgame_stats` 支持Thompson Sampling |
| **Embedding借用** | 相似游戏Embedding加权平均 |

---

## 八、扩展建议

### 8.1 未来可扩展项

1. **实时特征平台**
   - 引入Flink进行实时特征计算
   - Redis Streams存储事件流

2. **A/B测试增强**
   - 增加实验配置表
   - 推荐日志增加更多分流字段

3. **多租户支持**
   - 表增加`tenant_id`字段
   - 索引增加租户前缀

4. **国际化支持**
   - 游戏名称多语言存储
   - 分区域热门榜单

### 8.2 性能优化建议

| 优化项 | 建议 |
|--------|------|
| 读写分离 | MySQL主从分离，读走从库 |
| 缓存预热 | 启动时预加载热门游戏到Redis |
| 批量查询 | 使用`IN`代替多次单查询 |
| 异步写入 | 行为日志异步写入，减少延迟 |

---

## 九、总结

本设计方案针对游戏推荐系统的特殊需求，采用MySQL + Redis的混合存储架构：

1. **MySQL存储**：用户、游戏、行为等核心业务数据，以及离线计算结果
2. **Redis存储**：实时特征、热门榜单、Embedding向量、推荐缓存
3. **索引设计**：针对召回、排序等高频场景优化索引
4. **分区策略**：行为表和日志表按时间分区，支持数据生命周期管理

该设计完全支持文档中提到的六路召回策略（Item-CF、Embedding、内容、热门、新游戏、个性化），并为粗排/精排/重排提供了必要的特征存储支持。
```
```
```

