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

| 要求                | 说明                                         |
| ------------------- | -------------------------------------------- |
| **高QPS支持** | 所有表需支持 QPS > 1000 的在线查询           |
| **低延迟**    | 单表查询 P99 < 5ms                           |
| **特征就绪**  | 特征已预处理，算法模块直接使用，无需二次计算 |
| **版本控制**  | 支持特征版本管理，便于A/B测试                |

### 1.3 数据更新频率分类

| 类型                 | 更新频率    | 存储位置    | 说明                      |
| -------------------- | ----------- | ----------- | ------------------------- |
| **实时特征**   | 秒级~分钟级 | Redis       | Session特征、实时行为序列 |
| **近实时特征** | 小时级      | Redis/MySQL | 热门榜单、统计指标        |
| **离线特征**   | T+1         | MySQL       | 用户画像、游戏统计特征    |
| **模型产物**   | 每日/每周   | MySQL+Redis | Embedding、相似度矩阵     |

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
  
    -- 风险偏好 (基于RTP选择 + 投注行为综合计算)
    risk_preference TINYINT UNSIGNED DEFAULT 1 COMMENT '风险偏好: 0-low(保守) 1-medium 2-high(激进)',
    risk_score DECIMAL(4,3) DEFAULT 0.500 COMMENT '风险偏好分数 0-1 (0=保守,1=激进)',
  
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

---

#### 2.1.1 特征计算逻辑详解

> **时间定义约定**：
>
> - T：当前计算日期（通常为昨日23:59:59）
> - 近N天：`[T-N+1, T]` 闭区间
> - 时间衰减因子：`decay_factor = 0.95`，衰减公式 `weight = decay_factor ^ days_ago`

##### 一、用户基础特征

###### 1. lifecycle_stage（生命周期阶段）

| 属性               | 说明                                                         |
| ------------------ | ------------------------------------------------------------ |
| **业务含义** | 用户当前所处的生命周期阶段，影响召回策略配额分配和个性化程度 |
| **数据来源** | `user_behaviors` 表 + `users` 表                         |
| **取值范围** | 0-5（枚举值）                                                |

**计算逻辑：**

```python
def calculate_lifecycle_stage(user_id, register_date, today):
    """
    生命周期判定规则（按优先级从高到低）：

    5-churn(流失): 近30天无任何行为
    4-decline(衰退): 近7天活跃 < 近30天活跃的1/4，且近30天有行为
    3-mature(成熟): 注册>30天 且 近30天活跃>=7天
    2-active(活跃): 注册7-30天 且 近7天活跃>=3天
    1-growth(成长): 注册<7天 且 有过至少1次行为
    0-new(新用户): 注册<7天 且 无任何行为
    """
    register_days = (today - register_date).days
    active_days_7d = count_active_days(user_id, days=7)
    active_days_30d = count_active_days(user_id, days=30)

    # 判定优先级：流失 > 衰退 > 成熟 > 活跃 > 成长 > 新用户
    if active_days_30d == 0:
        return 5  # churn
    elif active_days_7d < active_days_30d / 4 and active_days_30d > 0:
        return 4  # decline
    elif register_days > 30 and active_days_30d >= 7:
        return 3  # mature
    elif 7 <= register_days <= 30 and active_days_7d >= 3:
        return 2  # active
    elif register_days < 7 and active_days_30d > 0:
        return 1  # growth
    else:
        return 0  # new

def count_active_days(user_id, days):
    """统计近N天的活跃天数（有任意行为即算活跃）"""
    sql = """
        SELECT COUNT(DISTINCT DATE(behavior_time))
        FROM user_behaviors
        WHERE user_id = :user_id
          AND behavior_time >= DATE_SUB(CURDATE(), INTERVAL :days DAY)
    """
    return execute(sql, user_id=user_id, days=days)
```

**边界情况：**

- 新注册用户（无行为）：`lifecycle_stage = 0`
- 注册当天有行为：`lifecycle_stage = 1`（growth）

---

###### 2. register_days（注册天数）

| 属性               | 说明                               |
| ------------------ | ---------------------------------- |
| **业务含义** | 用户生命周期长度，用于区分新老用户 |
| **数据来源** | `users.created_at`               |
| **计算公式** | `DATEDIFF(T, users.created_at)`  |
| **边界情况** | 注册当天 = 0                       |

---

###### 3. active_days_7d / active_days_30d（活跃天数）

| 属性               | 说明                                         |
| ------------------ | -------------------------------------------- |
| **业务含义** | 用户近期活跃程度，用于判断用户价值和推荐策略 |
| **数据来源** | `user_behaviors.behavior_time`             |
| **时间窗口** | 近7天 / 近30天                               |

**计算公式：**

```sql
-- active_days_7d
SELECT COUNT(DISTINCT DATE(behavior_time)) AS active_days_7d
FROM user_behaviors
WHERE user_id = :user_id
  AND behavior_time >= DATE_SUB(:T, INTERVAL 6 DAY)  -- 包含T当天，共7天
  AND behavior_time <= :T

-- active_days_30d (同理)
SELECT COUNT(DISTINCT DATE(behavior_time)) AS active_days_30d
FROM user_behaviors
WHERE user_id = :user_id
  AND behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
  AND behavior_time <= :T
```

**边界情况：**

- 无行为记录：`0`
- 最大值：`7` / `30`

---

###### 4. register_channel_id / register_device_id（注册渠道/设备）

| 属性               | 说明                                                  |
| ------------------ | ----------------------------------------------------- |
| **业务含义** | 冷启动特征，用于新用户的偏好推断                      |
| **数据来源** | `users.register_channel`, `users.register_device` |
| **编码方式** | 需要维护编码映射表                                    |

**边界情况：**

- 未知渠道/设备：`0`

---

##### 二、用户偏好特征

###### 5. pref_category_slots/crash/live/virtual（类目偏好度）

| 属性               | 说明                                           |
| ------------------ | ---------------------------------------------- |
| **业务含义** | 用户对各游戏类目的偏好程度，用于内容召回和精排 |
| **数据来源** | `user_behaviors` + `games.category_id`     |
| **取值范围** | [0, 1]，四个字段之和 = 1（概率分布）           |
| **时间窗口** | 近30天，带时间衰减                             |

**计算公式：**

```python
def calculate_category_preference(user_id, T, decay_factor=0.95):
    """
    类目偏好计算：
    1. 统计用户近30天在各类目的加权行为分
    2. 时间衰减：越近的行为权重越高
    3. 行为类型权重：play > click > view
    4. 时长加权：游戏时长越长权重越高
    5. 归一化为概率分布
    """

    # 行为类型权重
    ACTION_WEIGHTS = {
        'view': 1.0,
        'click': 3.0,
        'play': 10.0
    }

    # 获取近30天行为
    behaviors = query("""
        SELECT
            g.category_id,
            ub.behavior_type,
            ub.duration,
            DATEDIFF(:T, DATE(ub.behavior_time)) AS days_ago
        FROM user_behaviors ub
        JOIN games g ON ub.game_id = g.game_id
        WHERE ub.user_id = :user_id
          AND ub.behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
          AND ub.behavior_time <= :T
    """, user_id=user_id, T=T)

    # 初始化类目分数（加入平滑先验）
    PRIOR = 1.0  # Laplace平滑
    category_scores = {
        'slots': PRIOR,
        'crash': PRIOR,
        'live': PRIOR,
        'virtual': PRIOR
    }

    for row in behaviors:
        category = row['category_id']
        action = row['behavior_type']
        duration = row['duration'] or 0
        days_ago = row['days_ago']

        # 时间衰减权重
        time_weight = decay_factor ** days_ago

        # 行为类型权重
        action_weight = ACTION_WEIGHTS.get(action, 1.0)

        # 时长权重（play行为才有）: log(1 + duration/60) 转换为分钟后取对数
        duration_weight = 1.0
        if action == 'play' and duration > 0:
            duration_weight = math.log(1 + duration / 60)

        # 累加分数
        score = time_weight * action_weight * duration_weight
        category_scores[category] += score

    # 归一化为概率分布
    total = sum(category_scores.values())
    return {
        'pref_category_slots': round(category_scores['slots'] / total, 3),
        'pref_category_crash': round(category_scores['crash'] / total, 3),
        'pref_category_live': round(category_scores['live'] / total, 3),
        'pref_category_virtual': round(category_scores['virtual'] / total, 3)
    }
```

**权重参数说明：**

| 参数         | 值   | 说明                                         |
| ------------ | ---- | -------------------------------------------- |
| decay_factor | 0.95 | 时间衰减因子，30天前权重约为 0.95^30 ≈ 0.21 |
| view权重     | 1.0  | 基准权重                                     |
| click权重    | 3.0  | 点击比浏览价值更高                           |
| play权重     | 10.0 | 实际游戏是最强信号                           |
| PRIOR        | 1.0  | Laplace平滑，避免0概率                       |

**边界情况：**

- 新用户无行为：均匀分布 `[0.250, 0.250, 0.250, 0.250]`
- 只玩过一个类目：该类目偏好最高，但其他类目仍有先验值

---

###### 6. pref_provider_1/2/3（偏好提供商）

| 属性               | 说明                                       |
| ------------------ | ------------------------------------------ |
| **业务含义** | 用户偏好的游戏提供商，用于内容召回         |
| **数据来源** | `user_behaviors` + `games.provider_id` |
| **取值范围** | 提供商ID编码值                             |

**计算公式：**

```sql
-- 计算用户在各提供商的加权行为分，取Top3
WITH provider_scores AS (
    SELECT
        g.provider_id,
        SUM(
            CASE ub.behavior_type
                WHEN 'play' THEN 10 * LOG(1 + IFNULL(ub.duration, 0) / 60)
                WHEN 'click' THEN 3
                ELSE 1
            END
            * POW(0.95, DATEDIFF(:T, DATE(ub.behavior_time)))
        ) AS score
    FROM user_behaviors ub
    JOIN games g ON ub.game_id = g.game_id
    WHERE ub.user_id = :user_id
      AND ub.behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
    GROUP BY g.provider_id
    ORDER BY score DESC
    LIMIT 3
)
SELECT
    MAX(CASE WHEN rn = 1 THEN provider_id END) AS pref_provider_1,
    MAX(CASE WHEN rn = 2 THEN provider_id END) AS pref_provider_2,
    MAX(CASE WHEN rn = 3 THEN provider_id END) AS pref_provider_3
FROM (
    SELECT provider_id, ROW_NUMBER() OVER (ORDER BY score DESC) AS rn
    FROM provider_scores
) ranked
```

**边界情况：**

- 无行为/不足3个提供商：缺失位置填 `0`

---

###### 7. risk_preference / risk_score（风险偏好）

| 属性               | 说明                                                                   |
| ------------------ | ---------------------------------------------------------------------- |
| **业务含义** | 用户的风险承受偏好，反映用户是追求稳定小收益还是愿意承担风险博取大收益 |
| **数据来源** | `user_behaviors` + `overseas_casino_game.n_hit_rate`（RTP）        |
| **取值范围** | risk_preference: 0-2, risk_score: [0, 1]                               |
| **语义映射** | 0=保守(偏好高RTP), 1=中等, 2=激进(偏好低RTP)                           |

> **⚠️ 数据限制说明**
>
> 理想情况下，风险偏好应基于游戏的**波动性（Volatility）**计算，但当前业务数据库 `overseas_casino_game` 表中**没有波动性字段**，只有 `n_hit_rate`（RTP）字段。
>
> **RTP vs 波动性的区别：**
>
> - **RTP（Return to Player）**：长期理论返还率，如96%表示每投注100元理论上返还96元
> - **波动性（Volatility）**：收益的波动程度，高波动=稀少大奖，低波动=频繁小奖
>
> 两者是**独立维度**，高RTP游戏可以是高波动或低波动。但在缺少波动性数据时，我们采用**多维度综合评估**来近似用户风险偏好。

**计算公式（基于RTP + 投注行为综合评估）：**

```python
def calculate_risk_preference(user_id, T, decay_factor=0.95):
    """
    风险偏好计算 - 基于RTP偏好 + 投注行为模式综合评估

    由于缺少波动性数据，采用多维度信号：
    1. RTP偏好：偏好低RTP游戏 → 可能更愿意冒险
    2. 投注集中度：集中投注少数游戏 vs 分散投注
    3. 单次投注金额：大额投注 → 更高风险承受
    4. 游戏类型：Crash类游戏玩家通常更激进

    最终分数 = 0.4 * rtp_score + 0.2 * concentration_score + 0.2 * bet_score + 0.2 * gametype_score
    """

    # ============ 维度1: RTP偏好 (权重40%) ============
    rtp_data = query("""
        SELECT
            g.n_hit_rate AS rtp,
            g.s_data_type AS game_type,
            ub.duration,
            DATEDIFF(:T, DATE(ub.behavior_time)) AS days_ago
        FROM user_behaviors ub
        JOIN overseas_casino_game g ON ub.game_id = g.s_game_id
        WHERE ub.user_id = :user_id
          AND ub.behavior_type = 'play'
          AND ub.behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
          AND g.n_hit_rate IS NOT NULL
    """, user_id=user_id, T=T)

    if not rtp_data:
        # 无有效数据，返回默认中等
        return {'risk_preference': 1, 'risk_score': 0.500}

    # 计算加权平均RTP
    weighted_rtp_sum = 0
    weight_total = 0
    game_type_counts = {'RNG': 0, 'LC': 0, 'VSB': 0, 'CRASH': 0}

    for row in rtp_data:
        rtp = float(row['rtp'])
        duration = row['duration'] or 60
        days_ago = row['days_ago']
        game_type = row['game_type'] or 'RNG'

        weight = (decay_factor ** days_ago) * math.log(1 + duration / 60)
        weighted_rtp_sum += rtp * weight
        weight_total += weight

        # 统计游戏类型
        if 'crash' in game_type.lower() or 'aviator' in game_type.lower():
            game_type_counts['CRASH'] += weight
        else:
            game_type_counts[game_type] = game_type_counts.get(game_type, 0) + weight

    avg_rtp = weighted_rtp_sum / weight_total

    # RTP分数：RTP范围通常92-98%，使用敏感区间94-97%
    # 高RTP(>97%) → 保守(0), 低RTP(<94%) → 激进(1)
    # 注意：RTP与风险是反向关系
    RTP_LOW = 94.0   # 低于此值视为激进
    RTP_HIGH = 97.0  # 高于此值视为保守

    if avg_rtp >= RTP_HIGH:
        rtp_score = 0.0  # 保守
    elif avg_rtp <= RTP_LOW:
        rtp_score = 1.0  # 激进
    else:
        # 线性映射：97→0, 94→1
        rtp_score = (RTP_HIGH - avg_rtp) / (RTP_HIGH - RTP_LOW)

    # ============ 维度2: 游戏类型偏好 (权重20%) ============
    # Crash类游戏玩家通常风险偏好更高
    total_weight = sum(game_type_counts.values())
    crash_ratio = game_type_counts['CRASH'] / total_weight if total_weight > 0 else 0
    # Live Casino (LC) 玩家相对保守
    lc_ratio = game_type_counts.get('LC', 0) / total_weight if total_weight > 0 else 0

    gametype_score = crash_ratio * 1.0 + (1 - lc_ratio) * 0.3  # Crash玩家激进，LC玩家保守
    gametype_score = min(1.0, gametype_score)

    # ============ 维度3: 投注集中度 (权重20%) ============
    concentration_data = query("""
        SELECT
            COUNT(DISTINCT game_id) AS distinct_games,
            COUNT(*) AS total_plays
        FROM user_behaviors
        WHERE user_id = :user_id
          AND behavior_type = 'play'
          AND behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
    """, user_id=user_id, T=T)

    distinct_games = concentration_data['distinct_games'] or 1
    total_plays = concentration_data['total_plays'] or 1

    # 集中度 = 平均每游戏玩的次数，越高越集中
    concentration = total_plays / distinct_games
    # 高集中度（>5次/游戏）可能表示更专注/冒险
    concentration_score = min(1.0, (concentration - 1) / 4)  # 1次→0, 5次→1

    # ============ 维度4: 投注金额 (权重20%) ============
    bet_data = query("""
        SELECT AVG(bet_amount) AS avg_bet
        FROM user_behaviors
        WHERE user_id = :user_id
          AND behavior_type = 'play'
          AND bet_amount > 0
          AND behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
    """, user_id=user_id, T=T)

    avg_bet = bet_data['avg_bet'] or 0

    # 需要全局中位数作为基准（假设为10）
    GLOBAL_MEDIAN_BET = 10.0  # 需从数据统计获取

    # 高于中位数2倍视为高风险投注
    if avg_bet >= GLOBAL_MEDIAN_BET * 2:
        bet_score = 1.0
    elif avg_bet <= GLOBAL_MEDIAN_BET * 0.5:
        bet_score = 0.0
    else:
        bet_score = (avg_bet - GLOBAL_MEDIAN_BET * 0.5) / (GLOBAL_MEDIAN_BET * 1.5)

    # ============ 综合计算 ============
    risk_score = (
        0.40 * rtp_score +          # RTP偏好（主要信号）
        0.20 * gametype_score +     # 游戏类型
        0.20 * concentration_score + # 投注集中度
        0.20 * bet_score            # 投注金额
    )
    risk_score = round(max(0, min(1, risk_score)), 3)

    # 离散化（使用非均匀阈值，因为RTP分布集中）
    if risk_score < 0.35:
        risk_preference = 0  # 保守
    elif risk_score < 0.65:
        risk_preference = 1  # 中等
    else:
        risk_preference = 2  # 激进

    return {
        'risk_preference': risk_preference,
        'risk_score': risk_score,
        # 调试信息（可选，用于分析）
        '_debug': {
            'avg_rtp': round(avg_rtp, 2),
            'rtp_score': round(rtp_score, 3),
            'gametype_score': round(gametype_score, 3),
            'concentration_score': round(concentration_score, 3),
            'bet_score': round(bet_score, 3)
        }
    }
```

**风险偏好各维度权重说明：**

| 维度       | 权重 | 数据来源                             | 说明                     |
| ---------- | ---- | ------------------------------------ | ------------------------ |
| RTP偏好    | 40%  | `overseas_casino_game.n_hit_rate`  | 主要信号，低RTP=愿意冒险 |
| 游戏类型   | 20%  | `overseas_casino_game.s_data_type` | Crash类玩家更激进        |
| 投注集中度 | 20%  | `user_behaviors` 聚合              | 高集中度可能表示冒险     |
| 投注金额   | 20%  | `user_behaviors.bet_amount`        | 大额投注=高风险承受      |

**RTP与风险偏好的映射逻辑：**

```
RTP ≥ 97%  →  保守型（risk_score 趋向 0）
RTP 94-97% →  中等型（线性映射）
RTP ≤ 94%  →  激进型（risk_score 趋向 1）

注意：这是反向映射
高RTP = 理论收益稳定 = 用户追求稳定 = 保守
低RTP = 理论收益低但可能有大奖 = 用户追求博弈 = 激进
```

**边界情况：**

| 情况          | 处理方式                                            |
| ------------- | --------------------------------------------------- |
| 无play行为    | `risk_preference=1, risk_score=0.500`（默认中等） |
| RTP数据缺失   | 该维度得分使用0.5（中性值）                         |
| 投注金额全为0 | bet_score使用0.5                                    |
| 游戏类型未知  | gametype_score使用0.3（偏保守）                     |

**数据质量说明：**

> **当前方案的局限性：**
>
> 1. RTP分布集中在94-98%区间，区分度有限
> 2. 缺少真实波动性数据，多维度评估是近似方案
> 3. 全局中位数（GLOBAL_MEDIAN_BET）需要定期从数据统计更新
>
> **改进方案：**
>
> - 如果能从游戏供应商获取波动性数据，补充到 `overseas_casino_game` 表
> - 有了波动性数据后，可将 RTP 权重降至 20%，波动性权重提升至 40%

---

##### 三、用户行为统计特征

###### 8. total_play_count / total_play_duration / total_bet_amount / total_win_amount

| 属性               | 说明                           |
| ------------------ | ------------------------------ |
| **业务含义** | 用户累计行为统计，衡量用户价值 |
| **数据来源** | `user_behaviors` 表全量统计  |
| **更新方式** | 增量累加（不重算历史）         |

**计算公式：**

```sql
-- 增量更新策略（T+1任务）
-- 每天只统计T当天新增的数据，累加到现有值

-- Step 1: 计算T当天新增
SELECT
    COUNT(*) AS day_play_count,
    SUM(duration) AS day_play_duration,
    SUM(bet_amount) AS day_bet_amount,
    SUM(win_amount) AS day_win_amount
FROM user_behaviors
WHERE user_id = :user_id
  AND behavior_type = 'play'
  AND DATE(behavior_time) = :T

-- Step 2: 增量更新
UPDATE algo_user_features
SET
    total_play_count = total_play_count + :day_play_count,
    total_play_duration = total_play_duration + :day_play_duration,
    total_bet_amount = total_bet_amount + :day_bet_amount,
    total_win_amount = total_win_amount + :day_win_amount
WHERE user_id = :user_id
```

**边界情况：**

- 新用户：全部为 `0`

---

###### 9. play_count_7d / play_duration_7d / bet_amount_7d / distinct_games_7d

| 属性               | 说明                              |
| ------------------ | --------------------------------- |
| **业务含义** | 近7天活跃度指标，反映用户近期兴趣 |
| **数据来源** | `user_behaviors` 表             |
| **时间窗口** | 滑动窗口 [T-6, T]                 |
| **更新方式** | 每日全量重算（滑动窗口需要）      |

**计算公式：**

```sql
SELECT
    COUNT(*) AS play_count_7d,
    SUM(duration) AS play_duration_7d,
    SUM(bet_amount) AS bet_amount_7d,
    COUNT(DISTINCT game_id) AS distinct_games_7d
FROM user_behaviors
WHERE user_id = :user_id
  AND behavior_type = 'play'
  AND behavior_time >= DATE_SUB(:T, INTERVAL 6 DAY)
  AND behavior_time <= :T
```

**边界情况：**

- 近7天无play行为：全部为 `0`

---

###### 10. bet_pattern（投注模式）

| 属性               | 说明                                    |
| ------------------ | --------------------------------------- |
| **业务含义** | 用户投注风格，用于个性化推荐            |
| **数据来源** | `user_behaviors.bet_amount`           |
| **取值范围** | 0-small_frequent, 1-large_rare, 2-mixed |

**计算公式：**

```python
def calculate_bet_pattern(user_id, T):
    """
    投注模式判定：
    - small_frequent: 平均投注 < 中位数 且 投注频率 > 中位数
    - large_rare: 平均投注 > 中位数 且 投注频率 < 中位数
    - mixed: 其他情况

    中位数基于全局用户统计，每日更新一次
    """

    # 获取用户近30天投注统计
    stats = query("""
        SELECT
            AVG(bet_amount) AS avg_bet,
            COUNT(*) / 30.0 AS daily_frequency
        FROM user_behaviors
        WHERE user_id = :user_id
          AND behavior_type = 'play'
          AND bet_amount > 0
          AND behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
    """, user_id=user_id, T=T)

    avg_bet = stats['avg_bet'] or 0
    daily_freq = stats['daily_frequency'] or 0

    # 全局中位数（需提前计算）
    MEDIAN_BET = 10.0  # 假设值，需要从数据计算
    MEDIAN_FREQ = 2.0  # 假设值

    if avg_bet < MEDIAN_BET and daily_freq > MEDIAN_FREQ:
        return 0  # small_frequent
    elif avg_bet > MEDIAN_BET and daily_freq < MEDIAN_FREQ:
        return 1  # large_rare
    else:
        return 2  # mixed
```

**边界情况：**

- 无投注记录：`2`（mixed，默认中间值）

---

###### 11. avg_bet_amount / avg_session_duration

| 属性               | 说明                                 |
| ------------------ | ------------------------------------ |
| **业务含义** | 用户平均投注和会话时长，衡量参与深度 |
| **数据来源** | `user_behaviors` 表                |
| **时间窗口** | 近30天                               |

**计算公式：**

```sql
-- avg_bet_amount
SELECT AVG(bet_amount) AS avg_bet_amount
FROM user_behaviors
WHERE user_id = :user_id
  AND behavior_type = 'play'
  AND bet_amount > 0
  AND behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)

-- avg_session_duration（需要按session_id聚合）
SELECT AVG(session_duration) AS avg_session_duration
FROM (
    SELECT
        session_id,
        SUM(duration) AS session_duration
    FROM user_behaviors
    WHERE user_id = :user_id
      AND behavior_type = 'play'
      AND behavior_time >= DATE_SUB(:T, INTERVAL 29 DAY)
    GROUP BY session_id
) sessions
```

**边界情况：**

- 无投注：`avg_bet_amount = 0`
- 无会话：`avg_session_duration = 0`

---

##### 四、交叉统计特征

###### 12. ctr_category_slots/crash/live/virtual（类目CTR）

| 属性               | 说明                                         |
| ------------------ | -------------------------------------------- |
| **业务含义** | 用户在各类目的历史点击率，用于精排           |
| **数据来源** | `recommendation_logs` + `user_behaviors` |
| **取值范围** | [0, 1]                                       |
| **时间窗口** | 近30天                                       |

**计算公式：**

```python
def calculate_category_ctr(user_id, category_id, T, min_impressions=10):
    """
    类目CTR计算：
    CTR = 点击数 / 曝光数

    曝光：推荐日志中该类目游戏出现在推荐列表
    点击：用户对该类目游戏有click行为

    置信度调整：曝光不足时使用贝叶斯平滑
    """

    # 获取曝光和点击数
    stats = query("""
        SELECT
            COUNT(*) AS impressions,
            SUM(CASE WHEN ub.behavior_type = 'click' THEN 1 ELSE 0 END) AS clicks
        FROM recommendation_logs rl
        CROSS JOIN LATERAL JSON_TABLE(
            rl.recommended_games, '$[*]' COLUMNS(game_id VARCHAR(64) PATH '$.game_id')
        ) AS games
        JOIN algo_game_features g ON games.game_id = g.game_id
        LEFT JOIN user_behaviors ub
            ON rl.user_id = ub.user_id
            AND games.game_id = ub.game_id
            AND ub.behavior_type = 'click'
            AND ub.behavior_time BETWEEN rl.request_time AND DATE_ADD(rl.request_time, INTERVAL 1 HOUR)
        WHERE rl.user_id = :user_id
          AND g.category_id = :category_id
          AND rl.request_time >= DATE_SUB(:T, INTERVAL 29 DAY)
    """, user_id=user_id, category_id=category_id, T=T)

    impressions = stats['impressions']
    clicks = stats['clicks'] or 0

    # 全局类目CTR（先验）
    GLOBAL_CTR = {1: 0.05, 2: 0.08, 3: 0.04, 4: 0.06}  # 需要从数据计算
    prior_ctr = GLOBAL_CTR.get(category_id, 0.05)

    if impressions < min_impressions:
        # 贝叶斯平滑：使用全局CTR作为先验
        # 公式：(clicks + prior_ctr * weight) / (impressions + weight)
        weight = min_impressions
        smoothed_ctr = (clicks + prior_ctr * weight) / (impressions + weight)
        return round(smoothed_ctr, 4)
    else:
        return round(clicks / impressions, 4)
```

**贝叶斯平滑说明：**

- 当曝光数 < 10 时，使用全局CTR作为先验进行平滑
- 公式：`smoothed_ctr = (clicks + prior_ctr × weight) / (impressions + weight)`
- weight = 10，即等效于增加10次曝光

**边界情况：**

- 无曝光记录：使用全局CTR填充
- 曝光 < 10：使用贝叶斯平滑

---

##### 五、增量更新策略

###### 5.1 可增量更新的字段

| 字段                | 增量策略           |
| ------------------- | ------------------ |
| total_play_count    | `+= 当日新增`    |
| total_play_duration | `+= 当日新增`    |
| total_bet_amount    | `+= 当日新增`    |
| total_win_amount    | `+= 当日新增`    |
| register_days       | `+= 1`（每日+1） |

###### 5.2 需要滑动窗口重算的字段

| 字段                  | 重算原因             |
| --------------------- | -------------------- |
| active_days_7d/30d    | 滑动窗口，旧数据过期 |
| play_count_7d 等      | 滑动窗口             |
| pref_category_*       | 时间衰减权重变化     |
| pref_provider_*       | 时间衰减权重变化     |
| risk_preference/score | 时间衰减权重变化     |
| ctr_category_*        | 滑动窗口             |
| bet_pattern           | 依赖近30天数据       |
| avg_bet_amount        | 滑动窗口             |
| avg_session_duration  | 滑动窗口             |

###### 5.3 增量优化建议

```python
# 优化策略：分层更新

# 高频更新层（每日全量重算，约占50%字段）
HIGH_FREQ_FIELDS = [
    'lifecycle_stage', 'active_days_7d', 'active_days_30d',
    'play_count_7d', 'play_duration_7d', 'bet_amount_7d', 'distinct_games_7d'
]

# 中频更新层（每3天重算一次，约占30%字段）
MEDIUM_FREQ_FIELDS = [
    'pref_category_*', 'pref_provider_*', 'risk_preference', 'risk_score',
    'bet_pattern', 'avg_bet_amount', 'avg_session_duration'
]

# 低频更新层（每周重算，约占20%字段）
LOW_FREQ_FIELDS = [
    'ctr_category_*'  # CTR计算较重，可以降频
]

# 累加更新层（每日增量）
INCREMENTAL_FIELDS = [
    'total_play_count', 'total_play_duration',
    'total_bet_amount', 'total_win_amount', 'register_days'
]
```

---

##### 六、数据质量检查

```sql
-- 特征完整性检查
SELECT
    COUNT(*) AS total_users,
    SUM(CASE WHEN lifecycle_stage IS NULL THEN 1 ELSE 0 END) AS null_lifecycle,
    SUM(CASE WHEN pref_category_slots + pref_category_crash +
                  pref_category_live + pref_category_virtual
             NOT BETWEEN 0.99 AND 1.01 THEN 1 ELSE 0 END) AS invalid_pref_sum,
    SUM(CASE WHEN risk_score NOT BETWEEN 0 AND 1 THEN 1 ELSE 0 END) AS invalid_risk
FROM algo_user_features;

-- 特征分布检查
SELECT
    lifecycle_stage,
    COUNT(*) AS user_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) AS percentage
FROM algo_user_features
GROUP BY lifecycle_stage
ORDER BY lifecycle_stage;
```

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
    -- RTP数据来源: overseas_casino_game.n_hit_rate
    rtp DECIMAL(5,2) DEFAULT NULL COMMENT 'RTP返还率 (如96.50), 来源:n_hit_rate',

    -- ⚠️ 波动性字段：当前业务数据库无此数据，预留字段待供应商提供
    -- 如果未来获取到波动性数据，可启用以下字段
    volatility TINYINT UNSIGNED DEFAULT NULL COMMENT '波动性: 0-low 1-medium 2-high 3-very_high (待供应商提供)',
    volatility_score DECIMAL(3,2) DEFAULT NULL COMMENT '波动性数值 1.00-5.00 (待供应商提供)',

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

**数据来源映射：**

| algo_game_features 字段 | 业务表来源           | 业务字段             | 说明                                    |
| ----------------------- | -------------------- | -------------------- | --------------------------------------- |
| game_id                 | overseas_casino_game | s_game_id            | 游戏唯一标识                            |
| category_id             | overseas_casino_game | n_type               | 需要编码映射                            |
| provider_id             | overseas_casino_game | s_agent_code         | 需要编码映射                            |
| **rtp**           | overseas_casino_game | **n_hit_rate** | 直接使用，范围92-98                     |
| volatility              | -                    | -                    | **⚠️ 业务表无此字段，暂为NULL** |
| volatility_score        | -                    | -                    | **⚠️ 业务表无此字段，暂为NULL** |
| status                  | overseas_casino_game | n_status             | 0-禁用 1-启用                           |
| is_new                  | overseas_casino_game | n_category           | n_category IN (1,3) 视为新游戏          |
| is_featured             | overseas_casino_game | n_category           | n_category IN (2,3) 视为热门            |

**计算规则：**

- 热度分数：需归一化到0-1范围，公式：`score = log(1 + count) / log(1 + max_count)`
- 主题/特性位图：需要提供编码映射表
- 小时级任务：仅更新 `hot_score_*` 和 `play_count_*` 字段
- 状态同步：与业务系统 `overseas_casino_game.n_status` 保持一致

**波动性数据补充说明：**

> 当前 `volatility` 和 `volatility_score` 字段暂时为 NULL。
> 如果未来从游戏供应商（Pragmatic Play、Evolution等）获取到波动性数据，
> 需要建立数据同步机制，并更新用户风险偏好计算逻辑的权重分配。

---

#### 2.2.1 特征计算逻辑详解

> **时间定义约定**：
>
> - T：当前计算日期（通常为昨日23:59:59）
> - 近N天：`[T-N+1, T]` 闭区间
> - 近N小时：`[NOW - N hours, NOW]`

##### 一、游戏基础属性

###### 1. game_id（游戏ID）

| 属性               | 说明                               |
| ------------------ | ---------------------------------- |
| **业务含义** | 游戏唯一标识，贯穿整个推荐链路     |
| **数据来源** | `overseas_casino_game.s_game_id` |
| **更新频率** | 随游戏上架同步                     |
| **数据类型** | VARCHAR(64)，第三方游戏ID          |

**计算逻辑：**

```sql
-- 直接映射，保持原值
SELECT s_game_id AS game_id
FROM overseas_casino_game
WHERE n_status = 1  -- 只同步上线游戏
```

**边界情况：**

- 新上架游戏：实时同步或T+1批量新增
- 下架游戏：`status` 更新为0，但保留记录（用于历史数据关联）

---

###### 2. category_id（类目ID）

| 属性               | 说明                                                    |
| ------------------ | ------------------------------------------------------- |
| **业务含义** | 游戏所属大类，用于分类召回和类目偏好匹配                |
| **数据来源** | `overseas_casino_game.n_type` + `overseas_category` |
| **取值范围** | 0-unknown, 1-slots, 2-crash, 3-live, 4-virtual          |
| **更新频率** | T+1（游戏分类变更较少）                                 |

**编码映射表：**

```sql
-- 从业务表的分类关联提取并编码
-- overseas_casino_game.n_type → overseas_category.s_value.type

-- 编码映射规则
-- n_type 对应 overseas_category 表的 JSON(s_value.type)
-- 最终编码到 category_id

CREATE TABLE dim_category_mapping (
    business_type INT COMMENT 'overseas_casino_game.n_type',
    category_id TINYINT UNSIGNED COMMENT '算法模块类目ID',
    category_name VARCHAR(32) COMMENT '类目名称',
    PRIMARY KEY (business_type)
);

-- 示例映射数据（需根据实际 overseas_category 配置确定）
INSERT INTO dim_category_mapping VALUES
(1, 1, 'slots'),      -- 老虎机
(2, 2, 'crash'),      -- Crash游戏
(3, 3, 'live'),       -- 真人娱乐
(4, 4, 'virtual'),    -- 虚拟体育
(NULL, 0, 'unknown'); -- 未分类
```

**计算SQL：**

```sql
SELECT
    ocg.s_game_id AS game_id,
    COALESCE(dcm.category_id, 0) AS category_id
FROM overseas_casino_game ocg
LEFT JOIN dim_category_mapping dcm ON ocg.n_type = dcm.business_type
WHERE ocg.n_status = 1
```

**边界情况：**

- `n_type` 为 NULL：`category_id = 0` (unknown)
- `n_type` 不在映射表：`category_id = 0` (unknown)

---

###### 3. provider_id（提供商ID）

| 属性               | 说明                                       |
| ------------------ | ------------------------------------------ |
| **业务含义** | 游戏供应商，用于提供商偏好召回和多样性打散 |
| **数据来源** | `overseas_casino_game.s_agent_code`      |
| **更新频率** | T+1（提供商变更极少）                      |

**编码映射表：**

```sql
-- 提供商编码映射表
CREATE TABLE dim_provider_mapping (
    agent_code VARCHAR(50) COMMENT 'overseas_casino_game.s_agent_code',
    provider_id SMALLINT UNSIGNED COMMENT '算法模块提供商ID',
    provider_name VARCHAR(64) COMMENT '提供商名称',
    PRIMARY KEY (agent_code)
);

-- 示例映射数据（根据订单明细表的 s_provider 字段整理）
-- 实际 agent_code 需从 overseas_casino_game 表统计获取
INSERT INTO dim_provider_mapping VALUES
('PP', 1, 'Pragmatic Play'),
('EVO', 2, 'Evolution Gaming'),
('PG', 3, 'PG Soft'),
('SP', 4, 'SP Gaming'),
('NET', 5, 'NetEnt'),
-- ... 其他提供商
('UNKNOWN', 0, 'Unknown');
```

**计算SQL：**

```sql
SELECT
    ocg.s_game_id AS game_id,
    COALESCE(dpm.provider_id, 0) AS provider_id
FROM overseas_casino_game ocg
LEFT JOIN dim_provider_mapping dpm ON ocg.s_agent_code = dpm.agent_code
WHERE ocg.n_status = 1
```

**边界情况：**

- `s_agent_code` 为 NULL 或空：`provider_id = 0`
- 新提供商未入映射表：需定期扫描补充映射

---

###### 4. rtp（RTP返还率）

| 属性               | 说明                                       |
| ------------------ | ------------------------------------------ |
| **业务含义** | 游戏的长期理论返还率，用于用户风险偏好匹配 |
| **数据来源** | `overseas_casino_game.n_hit_rate`        |
| **取值范围** | 通常在 92.00-98.00 之间，部分游戏可能超出  |
| **更新频率** | T+1（RTP由供应商设定，较稳定）             |

**计算逻辑：**

```sql
-- 直接映射，保留2位小数
SELECT
    s_game_id AS game_id,
    ROUND(n_hit_rate, 2) AS rtp
FROM overseas_casino_game
WHERE n_status = 1
```

**数据处理规则：**

```python
def process_rtp(n_hit_rate):
    """
    RTP数据清洗规则：
    1. NULL值：保持NULL，精排模型需处理缺失
    2. 异常值检测：RTP通常在88-99%之间
    3. 超出范围的需人工审核
    """
    if n_hit_rate is None:
        return None

    rtp = float(n_hit_rate)

    # 异常值检测
    if rtp < 80 or rtp > 100:
        # 记录异常日志，返回NULL
        log_warning(f"RTP异常值: {rtp}")
        return None

    return round(rtp, 2)
```

**边界情况：**

| 情况                   | 处理方式                                 |
| ---------------------- | ---------------------------------------- |
| `n_hit_rate` 为 NULL | 保持 NULL，精排模型使用默认值（如95.00） |
| RTP < 50 或 > 100      | 视为异常，记录日志并置为 NULL            |
| 数据精度问题           | 四舍五入保留2位小数                      |

**在推荐系统中的作用：**

- 用户风险偏好匹配：高RTP（>97%）适合保守型用户，低RTP（<94%）适合激进型用户
- 精排模型特征输入

---

###### 5. volatility / volatility_score（波动性）

| 属性               | 说明                                                 |
| ------------------ | ---------------------------------------------------- |
| **业务含义** | 游戏收益的波动程度，高波动=稀少大奖，低波动=频繁小奖 |
| **数据来源** | **⚠️ 业务表无此字段，暂为 NULL**             |
| **取值范围** | volatility: 0-low 1-medium 2-high 3-very_high        |
| **更新频率** | 待供应商提供数据后启用                               |

**数据缺失处理方案：**

```python
def get_volatility_fallback(game_id, rtp, category_id, features):
    """
    波动性数据缺失的临时处理方案：
    基于现有数据推断波动性（仅作为降级方案）

    推断规则：
    1. Crash类游戏通常高波动 → 返回 2 (high)
    2. Live类游戏通常低波动 → 返回 0 (low)
    3. Slots根据RTP和特性推断
    """
    # 方案1：基于类目的默认值
    CATEGORY_DEFAULT_VOLATILITY = {
        1: 1,  # slots → medium
        2: 2,  # crash → high
        3: 0,  # live → low
        4: 1,  # virtual → medium
        0: 1,  # unknown → medium
    }

    # 方案2：如果有 Megaways 特性，通常是高波动
    if features and 'megaways' in features.lower():
        return 2  # high

    # 方案3：Jackpot游戏通常高波动
    if features and 'jackpot' in features.lower():
        return 2  # high

    return CATEGORY_DEFAULT_VOLATILITY.get(category_id, 1)
```

**未来数据补充方案：**

```sql
-- 当从供应商获取到波动性数据后，更新字段
UPDATE algo_game_features agf
JOIN supplier_game_data sgd ON agf.game_id = sgd.game_id
SET
    agf.volatility = CASE sgd.volatility_level
        WHEN 'low' THEN 0
        WHEN 'medium' THEN 1
        WHEN 'high' THEN 2
        WHEN 'very_high' THEN 3
        ELSE NULL
    END,
    agf.volatility_score = sgd.volatility_numeric
WHERE sgd.volatility_level IS NOT NULL
```

---

###### 6. min_bet / max_bet（投注范围）

| 属性               | 说明                                                 |
| ------------------ | ---------------------------------------------------- |
| **业务含义** | 游戏的投注金额限制，用于按用户投注能力过滤           |
| **数据来源** | **业务表无此字段**，需从订单数据统计或手动配置 |
| **更新频率** | T+1（投注范围较稳定）                                |

**统计计算方案：**

```sql
-- 从历史订单统计游戏的实际投注范围
-- 使用 P5 和 P95 作为有效投注范围
SELECT
    odg.s_game_id AS game_id,
    PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY oog.n_order_money) AS min_bet,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY oog.n_order_money) AS max_bet
FROM overseas_order_detail_game odg
JOIN overseas_order_game oog ON odg.n_order_id = oog.n_id
WHERE oog.n_status = 1
  AND oog.n_pay_status = 1
  AND oog.d_create_time >= UNIX_TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 30 DAY)) * 1000
GROUP BY odg.s_game_id
```

**默认值处理：**

| 情况               | min_bet | max_bet | 说明                 |
| ------------------ | ------- | ------- | -------------------- |
| 无订单数据         | 0.10    | 1000.00 | 使用平台默认范围     |
| 统计样本不足(<100) | 0.10    | 1000.00 | 样本太少，使用默认值 |
| 正常统计           | P5      | P95     | 使用统计分位数       |

---

##### 二、游戏状态属性

###### 7. status（游戏状态）

| 属性               | 说明                              |
| ------------------ | --------------------------------- |
| **业务含义** | 游戏当前状态，用于过滤不可用游戏  |
| **数据来源** | `overseas_casino_game.n_status` |
| **取值范围** | 0-下线, 1-上线, 2-维护            |
| **更新频率** | 实时同步（关键业务状态）          |

**映射逻辑：**

```sql
SELECT
    s_game_id AS game_id,
    CASE n_status
        WHEN 1 THEN 1  -- 启用 → 上线
        WHEN 0 THEN 0  -- 禁用 → 下线
        ELSE 2         -- 其他状态 → 维护
    END AS status
FROM overseas_casino_game
```

**同步策略：**

- 建议实时同步
- 状态变更直接影响推荐结果，需确保秒级同步

---

###### 8. is_new（是否新游戏）

| 属性               | 说明                                     |
| ------------------ | ---------------------------------------- |
| **业务含义** | 标识新上架游戏，用于新游戏召回和曝光控制 |
| **数据来源** | `overseas_casino_game.n_category`      |
| **取值范围** | 0-否, 1-是                               |
| **更新频率** | T+1                                      |

**计算逻辑：**

```sql
-- 基于 n_category 判断
-- n_category: 1=新游戏, 2=热门, 3=新且热门, 4=其他
SELECT
    s_game_id AS game_id,
    CASE
        WHEN n_category IN (1, 3) THEN 1  -- 新游戏 或 新且热门
        ELSE 0
    END AS is_new
FROM overseas_casino_game
WHERE n_status = 1
```

**备选方案（基于上线时间）：**

```sql
-- 如果有上线时间字段，可用时间计算
SELECT
    s_game_id AS game_id,
    CASE
        WHEN DATEDIFF(CURDATE(), FROM_UNIXTIME(d_create_time/1000)) <= 7 THEN 1
        ELSE 0
    END AS is_new
FROM overseas_casino_game
WHERE n_status = 1
```

---

###### 9. is_featured（是否运营推荐）

| 属性               | 说明                                   |
| ------------------ | -------------------------------------- |
| **业务含义** | 运营人工标记的推荐游戏，用于运营位召回 |
| **数据来源** | `overseas_casino_game.n_category`    |
| **取值范围** | 0-否, 1-是                             |
| **更新频率** | T+1（或运营后台变更时实时同步）        |

**计算逻辑：**

```sql
-- 基于 n_category 判断
-- n_category: 1=新游戏, 2=热门, 3=新且热门, 4=其他
SELECT
    s_game_id AS game_id,
    CASE
        WHEN n_category IN (2, 3) THEN 1  -- 热门 或 新且热门
        ELSE 0
    END AS is_featured
FROM overseas_casino_game
WHERE n_status = 1
```

---

###### 10. is_jackpot（是否有累积奖池）

| 属性               | 说明                                             |
| ------------------ | ------------------------------------------------ |
| **业务含义** | 标识有累积奖池的游戏，适合追求大奖的用户         |
| **数据来源** | `overseas_casino_game.s_features` 或单独配置表 |
| **取值范围** | 0-否, 1-是                                       |
| **更新频率** | T+1                                              |

**计算逻辑：**

```sql
-- 从 s_features 字段解析
SELECT
    s_game_id AS game_id,
    CASE
        WHEN LOWER(s_features) LIKE '%jackpot%' THEN 1
        WHEN LOWER(s_features) LIKE '%progressive%' THEN 1
        ELSE 0
    END AS is_jackpot
FROM overseas_casino_game
WHERE n_status = 1
```

---

###### 11. launch_days（上线天数）

| 属性               | 说明                                   |
| ------------------ | -------------------------------------- |
| **业务含义** | 游戏上线时长，用于生命周期判断         |
| **数据来源** | `overseas_casino_game.d_create_time` |
| **更新频率** | T+1（每日+1）                          |

**计算逻辑：**

```sql
SELECT
    s_game_id AS game_id,
    DATEDIFF(CURDATE(), DATE(FROM_UNIXTIME(d_create_time / 1000))) AS launch_days
FROM overseas_casino_game
WHERE n_status = 1
  AND d_create_time IS NOT NULL
```

**边界情况：**

| 情况                       | 处理方式            |
| -------------------------- | ------------------- |
| `d_create_time` 为 NULL  | `launch_days = 0` |
| 创建时间在未来（数据异常） | 记录日志，置为 0    |

---

###### 12. lifecycle_stage（游戏生命周期阶段）

| 属性               | 说明                                           |
| ------------------ | ---------------------------------------------- |
| **业务含义** | 游戏当前所处生命周期，影响曝光策略和权重计算   |
| **数据来源** | 综合 `launch_days`、热度趋势、活跃玩家数计算 |
| **取值范围** | 0-new, 1-growth, 2-mature, 3-decline           |
| **更新频率** | T+1                                            |

**计算逻辑：**

```python
def calculate_game_lifecycle(game_id, launch_days, play_count_7d, play_count_30d, unique_players_7d):
    """
    游戏生命周期判定规则：

    0-new(新游戏): 上线<=14天
    1-growth(成长期): 上线14-60天 且 热度上升
    2-mature(成熟期): 上线>60天 且 热度稳定
    3-decline(衰退期): 热度持续下降（7天热度 < 30天热度/4）
    """
    # 热度趋势判断
    avg_daily_play_30d = play_count_30d / 30 if play_count_30d else 0
    avg_daily_play_7d = play_count_7d / 7 if play_count_7d else 0

    # 热度上升: 近7天日均 > 近30天日均 * 1.1
    is_growing = avg_daily_play_7d > avg_daily_play_30d * 1.1
    # 热度下降: 近7天日均 < 近30天日均 * 0.5
    is_declining = avg_daily_play_7d < avg_daily_play_30d * 0.5

    # 生命周期判定（按优先级）
    if launch_days <= 14:
        return 0  # new
    elif is_declining and launch_days > 30:
        return 3  # decline
    elif launch_days <= 60 and is_growing:
        return 1  # growth
    else:
        return 2  # mature
```

**SQL实现：**

```sql
SELECT
    game_id,
    CASE
        WHEN launch_days <= 14 THEN 0  -- new
        WHEN launch_days > 30
             AND play_count_7d / 7 < play_count_30d / 30 * 0.5 THEN 3  -- decline
        WHEN launch_days <= 60
             AND play_count_7d / 7 > play_count_30d / 30 * 1.1 THEN 1  -- growth
        ELSE 2  -- mature
    END AS lifecycle_stage
FROM (
    SELECT
        game_id,
        launch_days,
        play_count_7d,
        -- 需要额外计算30天游戏次数
        (SELECT COUNT(*) FROM user_behaviors ub
         WHERE ub.game_id = agf.game_id
           AND ub.behavior_type = 'play'
           AND ub.behavior_time >= DATE_SUB(CURDATE(), INTERVAL 29 DAY)) AS play_count_30d
    FROM algo_game_features agf
) t
```

**生命周期与推荐策略关系：**

| 生命周期 | 曝光策略                          | 权重调整     |
| -------- | --------------------------------- | ------------ |
| new      | 增加曝光机会（Thompson Sampling） | boost × 1.2 |
| growth   | 正常推荐，保持曝光                | boost × 1.1 |
| mature   | 稳定推荐                          | boost × 1.0 |
| decline  | 减少曝光，给新游戏让位            | boost × 0.8 |

---

##### 三、多值属性编码

###### 13. themes_bitmap（主题标签位图）

| 属性               | 说明                                             |
| ------------------ | ------------------------------------------------ |
| **业务含义** | 游戏的主题标签集合（如：古埃及、神话、水果等）   |
| **数据来源** | `overseas_casino_game.s_features` 或运营配置表 |
| **编码方式** | 位图（Bitmap），每个位对应一个主题               |
| **更新频率** | T+1                                              |

**主题编码映射表：**

```sql
-- 主题编码表（位置从0开始）
CREATE TABLE dim_theme_encoding (
    theme_id SMALLINT UNSIGNED PRIMARY KEY COMMENT '主题ID',
    bit_position TINYINT UNSIGNED COMMENT '位图位置 0-63',
    theme_name VARCHAR(32) COMMENT '主题名称',
    theme_keywords VARCHAR(256) COMMENT '匹配关键词（逗号分隔）'
);

-- 示例数据
INSERT INTO dim_theme_encoding VALUES
(1, 0, 'egyptian', 'egypt,pharaoh,cleopatra,pyramid'),
(2, 1, 'mythology', 'zeus,olympus,god,goddess,thor'),
(3, 2, 'fruit', 'fruit,cherry,apple,orange,watermelon'),
(4, 3, 'asian', 'dragon,fortune,lucky,chinese,oriental'),
(5, 4, 'adventure', 'adventure,treasure,explorer,quest'),
(6, 5, 'fantasy', 'magic,wizard,fairy,fantasy,enchanted'),
(7, 6, 'animal', 'animal,safari,wildlife,jungle'),
(8, 7, 'classic', 'classic,retro,777,bar'),
(9, 8, 'irish', 'irish,leprechaun,rainbow,clover'),
(10, 9, 'horror', 'horror,vampire,zombie,halloween'),
-- ... 最多64个主题
```

**位图编码逻辑：**

```python
def encode_themes_bitmap(game_name, game_features, theme_encodings):
    """
    主题位图编码：
    1. 将游戏名称和特性文本与主题关键词匹配
    2. 匹配成功则设置对应位为1
    3. 返回64位整数

    示例：
    - 游戏名含 "Zeus" → 匹配 mythology → 设置 bit 1
    - 位图: 0000...0010 → themes_bitmap = 2
    """
    bitmap = 0
    combined_text = f"{game_name} {game_features}".lower()

    for encoding in theme_encodings:
        keywords = encoding['theme_keywords'].lower().split(',')
        for keyword in keywords:
            if keyword.strip() in combined_text:
                # 设置对应位为1
                bitmap |= (1 << encoding['bit_position'])
                break  # 匹配一个关键词即可

    return bitmap

# 示例
# game_name = "Gates of Olympus"
# game_features = "mythology, free spins, multiplier"
# 匹配: mythology (bit 1) → bitmap = 2
```

**SQL批量计算：**

```sql
-- 使用位运算构建位图
SELECT
    ocg.s_game_id AS game_id,
    SUM(
        CASE
            WHEN LOWER(CONCAT(ocg.s_game_name, ' ', COALESCE(ocg.s_features, '')))
                 REGEXP dte.theme_keywords_regex THEN POW(2, dte.bit_position)
            ELSE 0
        END
    ) AS themes_bitmap
FROM overseas_casino_game ocg
CROSS JOIN dim_theme_encoding dte
WHERE ocg.n_status = 1
GROUP BY ocg.s_game_id
```

---

###### 14. features_bitmap（特性标签位图）

| 属性               | 说明                                                      |
| ------------------ | --------------------------------------------------------- |
| **业务含义** | 游戏的功能特性集合（如：Megaways、免费旋转、乘数等）      |
| **数据来源** | `overseas_casino_game.s_features` + `n_frb_available` |
| **编码方式** | 位图（Bitmap），每个位对应一个特性                        |
| **更新频率** | T+1                                                       |

**特性编码映射表：**

```sql
CREATE TABLE dim_feature_encoding (
    feature_id SMALLINT UNSIGNED PRIMARY KEY,
    bit_position TINYINT UNSIGNED COMMENT '位图位置 0-63',
    feature_name VARCHAR(32),
    feature_keywords VARCHAR(256)
);

INSERT INTO dim_feature_encoding VALUES
(1, 0, 'megaways', 'megaways'),
(2, 1, 'free_spins', 'free spin,freespin,free round'),
(3, 2, 'multiplier', 'multiplier,multiply'),
(4, 3, 'wild', 'wild,expanding wild,sticky wild'),
(5, 4, 'scatter', 'scatter'),
(6, 5, 'bonus_game', 'bonus game,bonus round,mini game'),
(7, 6, 'jackpot', 'jackpot,progressive'),
(8, 7, 'buy_feature', 'buy feature,bonus buy'),
(9, 8, 'cascade', 'cascade,tumble,avalanche'),
(10, 9, 'hold_spin', 'hold,respin'),
(11, 10, 'cluster_pay', 'cluster,cluster pay');
```

**计算逻辑（含特殊字段处理）：**

```python
def encode_features_bitmap(game_id, s_features, n_frb_available, feature_encodings):
    """
    特性位图编码：
    1. 从 s_features 文本匹配特性关键词
    2. 特殊处理 n_frb_available 字段（免费旋转）

    n_frb_available = 1 → 强制设置 free_spins 位
    """
    bitmap = 0
    features_text = (s_features or '').lower()

    # 遍历所有特性编码
    for encoding in feature_encodings:
        keywords = encoding['feature_keywords'].lower().split(',')
        for keyword in keywords:
            if keyword.strip() in features_text:
                bitmap |= (1 << encoding['bit_position'])
                break

    # 特殊处理：n_frb_available 字段
    if n_frb_available == 1:
        # free_spins 在 bit_position = 1
        bitmap |= (1 << 1)

    return bitmap
```

---

###### 15. theme_1 / theme_2 / theme_3（Top3主题ID）

| 属性               | 说明                                |
| ------------------ | ----------------------------------- |
| **业务含义** | 游戏的主要主题，用于快速主题匹配    |
| **数据来源** | 从 `themes_bitmap` 解析或人工标注 |
| **更新频率** | T+1                                 |

**计算逻辑：**

```python
def extract_top3_themes(themes_bitmap, theme_priority):
    """
    从位图中提取Top3主题ID

    theme_priority: 主题优先级列表（按业务重要性排序）
    """
    themes = []

    for theme in theme_priority:
        bit_position = theme['bit_position']
        if themes_bitmap & (1 << bit_position):
            themes.append(theme['theme_id'])
            if len(themes) >= 3:
                break

    # 不足3个用0填充
    while len(themes) < 3:
        themes.append(0)

    return themes[0], themes[1], themes[2]
```

---

##### 四、热度统计特征（小时级更新）

###### 16. hot_score_1h / hot_score_24h / hot_score_7d（热度分数）

| 属性               | 说明                                                          |
| ------------------ | ------------------------------------------------------------- |
| **业务含义** | 归一化的热度分数，用于热门召回排序                            |
| **数据来源** | `overseas_order_game` + `overseas_order_detail_game`      |
| **取值范围** | [0, 1]，归一化分数                                            |
| **更新频率** | 小时级（hot_score_1h）/ 小时级（hot_score_24h, hot_score_7d） |

**归一化公式：**

```
hot_score = log(1 + play_count) / log(1 + max_play_count)

其中：
- play_count: 该游戏在时间窗口内的游戏次数
- max_play_count: 所有游戏在同一时间窗口内的最大游戏次数
```

**计算SQL（1小时热度）：**

```sql
-- Step 1: 计算各游戏1小时游戏次数
WITH hourly_play AS (
    SELECT
        odg.s_game_id AS game_id,
        COUNT(*) AS play_count
    FROM overseas_order_game oog
    JOIN overseas_order_detail_game odg ON oog.n_id = odg.n_order_id
    WHERE oog.n_status = 1
      AND oog.n_pay_status = 1
      AND oog.d_create_time >= (UNIX_TIMESTAMP(NOW()) - 3600) * 1000  -- 1小时内
    GROUP BY odg.s_game_id
),
max_count AS (
    SELECT MAX(play_count) AS max_play FROM hourly_play
)
-- Step 2: 归一化计算
SELECT
    hp.game_id,
    hp.play_count AS play_count_1h,
    ROUND(LOG(1 + hp.play_count) / LOG(1 + mc.max_play), 5) AS hot_score_1h
FROM hourly_play hp
CROSS JOIN max_count mc
```

**24小时和7天热度计算：**

```sql
-- 24小时热度
WITH daily_play AS (
    SELECT
        odg.s_game_id AS game_id,
        COUNT(*) AS play_count
    FROM overseas_order_game oog
    JOIN overseas_order_detail_game odg ON oog.n_id = odg.n_order_id
    WHERE oog.n_status = 1
      AND oog.n_pay_status = 1
      AND oog.d_create_time >= (UNIX_TIMESTAMP(NOW()) - 86400) * 1000  -- 24小时内
    GROUP BY odg.s_game_id
),
max_count AS (
    SELECT MAX(play_count) AS max_play FROM daily_play
)
SELECT
    dp.game_id,
    dp.play_count AS play_count_24h,
    ROUND(LOG(1 + dp.play_count) / LOG(1 + mc.max_play), 5) AS hot_score_24h
FROM daily_play dp
CROSS JOIN max_count mc

-- 7天热度（类似逻辑，时间窗口改为 7 * 86400 秒）
```

**热度分数特点：**

| 分数范围  | 含义               | 游戏数占比(估) |
| --------- | ------------------ | -------------- |
| 0.8 - 1.0 | 超热门（头部游戏） | ~1%            |
| 0.5 - 0.8 | 热门               | ~10%           |
| 0.2 - 0.5 | 中等热度           | ~30%           |
| 0.0 - 0.2 | 低热度/长尾        | ~59%           |

**边界情况：**

| 情况              | 处理方式                     |
| ----------------- | ---------------------------- |
| 无游戏次数        | `hot_score = 0`            |
| 所有游戏次数都为0 | `hot_score = 0`（避免除0） |
| 新游戏            | 可能热度偏低，需结合探索策略 |

---

###### 17. play_count_1h / play_count_24h / play_count_7d（原始游戏次数）

| 属性               | 说明                                 |
| ------------------ | ------------------------------------ |
| **业务含义** | 原始游戏次数，用于召回时的绝对值排序 |
| **数据来源** | `overseas_order_game` 订单统计     |
| **更新频率** | 小时级                               |

**计算逻辑（见上文热度分数计算的中间结果）**

---

###### 18. unique_players_7d（7天独立玩家数）

| 属性               | 说明                                       |
| ------------------ | ------------------------------------------ |
| **业务含义** | 衡量游戏的用户覆盖广度                     |
| **数据来源** | `overseas_order_game.n_user_id` 去重统计 |
| **更新频率** | T+1（或小时级）                            |

**计算SQL：**

```sql
SELECT
    odg.s_game_id AS game_id,
    COUNT(DISTINCT oog.n_user_id) AS unique_players_7d
FROM overseas_order_game oog
JOIN overseas_order_detail_game odg ON oog.n_id = odg.n_order_id
WHERE oog.n_status = 1
  AND oog.n_pay_status = 1
  AND oog.n_user_id > 1100000  -- 排除测试用户
  AND oog.d_create_time >= (UNIX_TIMESTAMP(CURDATE()) - 7 * 86400) * 1000
GROUP BY odg.s_game_id
```

---

##### 五、效果指标（T+1更新）

###### 19. ctr_7d（7天点击率）

| 属性               | 说明                                      |
| ------------------ | ----------------------------------------- |
| **业务含义** | 游戏被曝光后的点击概率，反映吸引力        |
| **数据来源** | `algo_recommendation_log`（推荐日志表） |
| **计算公式** | `CTR = 点击数 / 曝光数`                 |
| **更新频率** | T+1                                       |

**计算SQL：**

```sql
-- 依赖推荐日志表的曝光和点击统计
WITH game_impressions AS (
    SELECT
        jt.game_id,
        COUNT(*) AS impressions,
        SUM(CASE WHEN jt.game_id IN (
            SELECT JSON_UNQUOTE(JSON_EXTRACT(arl.clicked_games, CONCAT('$[', numbers.n, ']')))
            FROM (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4) numbers
            WHERE JSON_EXTRACT(arl.clicked_games, CONCAT('$[', numbers.n, ']')) IS NOT NULL
        ) THEN 1 ELSE 0 END) AS clicks
    FROM algo_recommendation_log arl
    CROSS JOIN JSON_TABLE(
        arl.recommended_games,
        '$[*]' COLUMNS(game_id VARCHAR(64) PATH '$.game_id')
    ) AS jt
    WHERE arl.log_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
    GROUP BY jt.game_id
)
SELECT
    game_id,
    ROUND(clicks / NULLIF(impressions, 0), 4) AS ctr_7d
FROM game_impressions
```

**贝叶斯平滑处理：**

```python
def calculate_ctr_with_smoothing(clicks, impressions, global_ctr=0.05, min_impressions=100):
    """
    CTR贝叶斯平滑：
    当曝光数不足时，使用全局CTR作为先验进行平滑

    公式: smoothed_ctr = (clicks + global_ctr * weight) / (impressions + weight)
    weight = min_impressions（等效增加100次曝光）
    """
    if impressions < min_impressions:
        weight = min_impressions
        smoothed_ctr = (clicks + global_ctr * weight) / (impressions + weight)
        return round(smoothed_ctr, 4)
    else:
        return round(clicks / impressions, 4) if impressions > 0 else 0.0
```

**边界情况：**

| 情况          | 处理方式              |
| ------------- | --------------------- |
| 无曝光数据    | 使用全局CTR（约0.05） |
| 曝光数 < 100  | 贝叶斯平滑            |
| 曝光数 >= 100 | 直接计算实际CTR       |

---

###### 20. cvr_7d（7天转化率）

| 属性               | 说明                                   |
| ------------------ | -------------------------------------- |
| **业务含义** | 点击后开始游戏的概率，反映游戏留存能力 |
| **数据来源** | `algo_recommendation_log`            |
| **计算公式** | `CVR = 游戏次数 / 点击数`            |
| **更新频率** | T+1                                    |

**计算逻辑：**

```sql
-- 从推荐日志统计点击→游戏转化
WITH game_clicks AS (
    SELECT
        jt.game_id,
        COUNT(*) AS clicks
    FROM algo_recommendation_log arl
    CROSS JOIN JSON_TABLE(
        arl.clicked_games,
        '$[*]' COLUMNS(game_id VARCHAR(64) PATH '$')
    ) AS jt
    WHERE arl.log_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
    GROUP BY jt.game_id
),
game_plays AS (
    SELECT
        jt.game_id,
        COUNT(*) AS plays
    FROM algo_recommendation_log arl
    CROSS JOIN JSON_TABLE(
        arl.played_games,
        '$[*]' COLUMNS(game_id VARCHAR(64) PATH '$')
    ) AS jt
    WHERE arl.log_date >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
    GROUP BY jt.game_id
)
SELECT
    gc.game_id,
    ROUND(COALESCE(gp.plays, 0) / NULLIF(gc.clicks, 0), 4) AS cvr_7d
FROM game_clicks gc
LEFT JOIN game_plays gp ON gc.game_id = gp.game_id
```

**贝叶斯平滑**：同CTR处理方式

---

###### 21. avg_session_duration（平均游戏时长）

| 属性               | 说明                                 |
| ------------------ | ------------------------------------ |
| **业务含义** | 玩家平均每次游戏的时长，反映游戏粘性 |
| **数据来源** | `user_behaviors` 或订单时间差估算  |
| **更新频率** | T+1                                  |

**计算方案（基于订单时间差估算）：**

```sql
-- 如果没有明确的时长字段，使用同一用户连续订单的时间差估算
WITH ordered_plays AS (
    SELECT
        odg.s_game_id AS game_id,
        oog.n_user_id,
        oog.d_buy_time,
        LEAD(oog.d_buy_time) OVER (
            PARTITION BY oog.n_user_id, odg.s_game_id
            ORDER BY oog.d_buy_time
        ) AS next_buy_time
    FROM overseas_order_game oog
    JOIN overseas_order_detail_game odg ON oog.n_id = odg.n_order_id
    WHERE oog.n_status = 1
      AND oog.d_create_time >= (UNIX_TIMESTAMP(CURDATE()) - 7 * 86400) * 1000
)
SELECT
    game_id,
    ROUND(AVG(
        CASE
            WHEN (next_buy_time - d_buy_time) / 1000 BETWEEN 10 AND 3600
            THEN (next_buy_time - d_buy_time) / 1000
            ELSE NULL
        END
    )) AS avg_session_duration
FROM ordered_plays
GROUP BY game_id
```

**边界情况：**

- 时间差 < 10秒：视为同一投注，不计入
- 时间差 > 3600秒：视为新会话，不计入

---

###### 22. avg_bet_amount（平均单次投注）

| 属性               | 说明                                  |
| ------------------ | ------------------------------------- |
| **业务含义** | 玩家在该游戏的平均投注金额            |
| **数据来源** | `overseas_order_game.n_order_money` |
| **更新频率** | T+1                                   |

**计算SQL：**

```sql
SELECT
    odg.s_game_id AS game_id,
    ROUND(AVG(oog.n_order_money), 2) AS avg_bet_amount
FROM overseas_order_game oog
JOIN overseas_order_detail_game odg ON oog.n_id = odg.n_order_id
WHERE oog.n_status = 1
  AND oog.n_pay_status = 1
  AND oog.n_order_money > 0
  AND oog.d_create_time >= (UNIX_TIMESTAMP(CURDATE()) - 7 * 86400) * 1000
GROUP BY odg.s_game_id
```

---

###### 23. avg_rating / favorite_count（评分与收藏）

| 属性               | 说明                               |
| ------------------ | ---------------------------------- |
| **业务含义** | 用户对游戏的主观评价               |
| **数据来源** | **⚠️ 需要新增评分/收藏表** |
| **更新频率** | T+1                                |

**临时处理方案：**

```sql
-- 暂无评分收藏表，使用默认值
UPDATE algo_game_features
SET
    avg_rating = 0.00,
    favorite_count = 0
WHERE avg_rating IS NULL
```

---

##### 六、运营权重

###### 24. boost_weight（运营加权）

| 属性               | 说明                                           |
| ------------------ | ---------------------------------------------- |
| **业务含义** | 运营人工设置的权重，用于调整游戏曝光优先级     |
| **数据来源** | 运营后台配置或 `overseas_casino_game.n_sort` |
| **取值范围** | [0.50, 2.00]，1.00为基准                       |
| **更新频率** | 运营变更时实时同步                             |

**权重策略说明：**

| 权重值 | 适用场景                       |
| ------ | ------------------------------ |
| 2.00   | 重点推广游戏（新上线、合作款） |
| 1.50   | 运营推荐游戏                   |
| 1.00   | 普通游戏（默认）               |
| 0.75   | 低优先级游戏                   |
| 0.50   | 降权游戏（待下线、低质量）     |

**计算逻辑（基于n_sort）：**

```sql
-- 将 n_sort 映射到 boost_weight
-- 假设 n_sort 越大优先级越高，范围 1-100
SELECT
    s_game_id AS game_id,
    CASE
        WHEN n_sort >= 90 THEN 2.00
        WHEN n_sort >= 70 THEN 1.50
        WHEN n_sort >= 30 THEN 1.00
        WHEN n_sort >= 10 THEN 0.75
        ELSE 0.50
    END AS boost_weight
FROM overseas_casino_game
WHERE n_status = 1
```

**或从运营配置表读取：**

```sql
-- 如果有独立的运营配置表
SELECT
    agf.game_id,
    COALESCE(obc.boost_weight, 1.00) AS boost_weight
FROM algo_game_features agf
LEFT JOIN ops_boost_config obc ON agf.game_id = obc.game_id
```

---

##### 七、更新策略汇总

###### 7.1 字段更新频率分类

| 更新频率         | 字段列表                                                                                                                                                                                                                                                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **小时级** | `hot_score_1h`, `hot_score_24h`, `hot_score_7d`, `play_count_1h`, `play_count_24h`, `play_count_7d`                                                                                                                                                                                                                                  |
| **T+1**    | `category_id`, `provider_id`, `rtp`, `min_bet`, `max_bet`, `is_new`, `is_featured`, `is_jackpot`, `launch_days`, `lifecycle_stage`, `themes_bitmap`, `features_bitmap`, `theme_1/2/3`, `unique_players_7d`, `ctr_7d`, `cvr_7d`, `avg_session_duration`, `avg_bet_amount`, `avg_rating`, `favorite_count` |
| **实时**   | `status`, `boost_weight`                                                                                                                                                                                                                                                                                                                     |

###### 7.2 ETL任务设计

```python
# 小时级任务（每小时执行）
HOURLY_ETL_FIELDS = [
    'hot_score_1h', 'hot_score_24h', 'hot_score_7d',
    'play_count_1h', 'play_count_24h', 'play_count_7d'
]

# T+1任务（每日凌晨执行）
DAILY_ETL_FIELDS = [
    # 基础属性
    'category_id', 'provider_id', 'rtp', 'min_bet', 'max_bet',
    # 状态属性
    'is_new', 'is_featured', 'is_jackpot', 'launch_days', 'lifecycle_stage',
    # 多值属性
    'themes_bitmap', 'features_bitmap', 'theme_1', 'theme_2', 'theme_3',
    # 效果指标
    'unique_players_7d', 'ctr_7d', 'cvr_7d',
    'avg_session_duration', 'avg_bet_amount',
    'avg_rating', 'favorite_count'
]

# 实时同步任务（CDC）
REALTIME_SYNC_FIELDS = ['status', 'boost_weight']
```

###### 7.3 数据质量检查SQL

```sql
-- 游戏特征完整性检查
SELECT
    COUNT(*) AS total_games,
    SUM(CASE WHEN category_id = 0 THEN 1 ELSE 0 END) AS unknown_category,
    SUM(CASE WHEN provider_id = 0 THEN 1 ELSE 0 END) AS unknown_provider,
    SUM(CASE WHEN rtp IS NULL THEN 1 ELSE 0 END) AS null_rtp,
    SUM(CASE WHEN hot_score_7d = 0 THEN 1 ELSE 0 END) AS zero_hot_score,
    SUM(CASE WHEN status NOT IN (0, 1, 2) THEN 1 ELSE 0 END) AS invalid_status
FROM algo_game_features;

-- 热度分数分布检查
SELECT
    CASE
        WHEN hot_score_7d >= 0.8 THEN 'top_hot'
        WHEN hot_score_7d >= 0.5 THEN 'hot'
        WHEN hot_score_7d >= 0.2 THEN 'medium'
        ELSE 'low'
    END AS hot_tier,
    COUNT(*) AS game_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) AS percentage
FROM algo_game_features
WHERE status = 1
GROUP BY 1
ORDER BY MIN(hot_score_7d) DESC;

-- 生命周期分布检查
SELECT
    lifecycle_stage,
    COUNT(*) AS game_count
FROM algo_game_features
WHERE status = 1
GROUP BY lifecycle_stage
ORDER BY lifecycle_stage;
```

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

| 表/Key                                   | 召回            | 粗排 | 精排    | 重排 | 日志 |
| ---------------------------------------- | --------------- | ---- | ------- | ---- | ---- |
| **MySQL: algo_user_features**      | ✓(内容)        |      | ✓      |      |      |
| **MySQL: algo_game_features**      | ✓(热门/新游戏) | ✓   | ✓      | ✓   |      |
| **MySQL: algo_game_similarity**    | ✓(Item-CF)     |      |         |      |      |
| **MySQL: algo_user_recall**        | ✓(预计算)      |      |         |      |      |
| **MySQL: algo_recommendation_log** |                 |      |         |      | ✓   |
| **Redis: algo:user:realtime**      |                 | ✓   | ✓      | ✓   |      |
| **Redis: algo:user:behavior_seq**  | ✓(Item-CF)     |      | ✓(DIN) |      |      |
| **Redis: algo:hot:***              | ✓(热门)        |      |         |      |      |
| **Redis: algo:game:similar**       | ✓(Item-CF)     |      |         |      |      |
| **Redis: algo:emb:***              | ✓(Embedding)   |      |         |      |      |
| **Redis: algo:newgame:stats**      | ✓(新游戏)      |      |         |      |      |
| **Redis: algo:rec:cache**          |                 |      |         |      | ✓   |

---

## 五、数据更新频率汇总

### 5.1 实时更新（秒级）

| 数据                           | 触发条件        | 更新方式         |
| ------------------------------ | --------------- | ---------------- |
| Redis: algo:user:realtime      | 用户任意行为    | 行为服务直接写入 |
| Redis: algo:user:behavior_seq  | 用户行为        | 行为服务 LPUSH   |
| Redis: algo:newgame:stats      | 新游戏曝光/点击 | 行为服务 HINCRBY |
| MySQL: algo_recommendation_log | 推荐请求        | 推荐服务异步写入 |

### 5.2 近实时更新（分钟~小时级）

| 数据                                   | 更新频率 | 更新方式     |
| -------------------------------------- | -------- | ------------ |
| Redis: algo:hot:global                 | 5分钟    | 定时任务聚合 |
| Redis: algo:hot:category:*             | 1小时    | 定时任务聚合 |
| MySQL: algo_game_features.hot_score_*  | 1小时    | 定时任务更新 |
| MySQL: algo_game_features.play_count_* | 1小时    | 定时任务更新 |

### 5.3 离线更新（T+1）

| 数据                                   | 更新时间 | 更新方式           |
| -------------------------------------- | -------- | ------------------ |
| MySQL: algo_user_features              | 每日凌晨 | Spark/Hive ETL     |
| MySQL: algo_game_features (非热度字段) | 每日凌晨 | Spark/Hive ETL     |
| MySQL: algo_game_similarity            | 每日凌晨 | Item-CF 离线计算   |
| MySQL: algo_user_recall                | 每日凌晨 | 离线召回预计算     |
| Redis: algo:game:similar:*             | 每日凌晨 | 从 MySQL 同步      |
| Redis: algo:emb:user:*                 | 每日凌晨 | Embedding 模型产出 |

### 5.4 周期更新（每周）

| 数据                   | 更新时间 | 更新方式             |
| ---------------------- | -------- | -------------------- |
| Redis: algo:emb:game:* | 每周     | Embedding 模型重训练 |

---

## 六、索引策略说明

### 6.1 MySQL 索引设计原则

| 原则                         | 说明                                             |
| ---------------------------- | ------------------------------------------------ |
| **主键查询优先**       | 用户特征、游戏特征表以主键查询为主，无需额外索引 |
| **覆盖索引**           | 召回查询尽量使用覆盖索引，避免回表               |
| **排序字段在索引末尾** | 如 `(category_id, status, hot_score_7d DESC)`  |
| **分区裁剪**           | 日志表按日期分区，查询时带上日期条件             |

### 6.2 Redis 访问模式

| 数据结构   | 访问模式        | 时间复杂度  |
| ---------- | --------------- | ----------- |
| Hash       | HGETALL / HMGET | O(N) / O(K) |
| List       | LRANGE 0 49     | O(N)        |
| Sorted Set | ZREVRANGE 0 29  | O(log(N)+M) |
| String     | GET             | O(1)        |

---

## 七、给大数据工程师的 ETL 清单

### 7.1 每日 T+1 任务

| 任务                | 输入                 | 输出                      | 优先级 |
| ------------------- | -------------------- | ------------------------- | ------ |
| 用户特征计算        | 用户表 + 行为表      | algo_user_features        | P0     |
| 游戏特征计算        | 游戏表 + 行为表      | algo_game_features        | P0     |
| Item-CF 相似度计算  | 行为表               | algo_game_similarity      | P0     |
| 用户召回预计算      | 相似度 + 用户行为    | algo_user_recall          | P1     |
| 用户 Embedding 更新 | 行为表               | Redis algo:emb:user:*     | P1     |
| 游戏相似度同步      | algo_game_similarity | Redis algo:game:similar:* | P0     |

### 7.2 小时级任务

| 任务         | 输入   | 输出                           | 优先级 |
| ------------ | ------ | ------------------------------ | ------ |
| 热门榜单更新 | 行为表 | Redis algo:hot:*               | P0     |
| 游戏热度更新 | 行为表 | algo_game_features.hot_score_* | P0     |

### 7.3 实时任务

| 任务             | 触发          | 输出                           | 优先级 |
| ---------------- | ------------- | ------------------------------ | ------ |
| 用户实时特征更新 | 用户行为事件  | Redis algo:user:realtime:*     | P0     |
| 用户行为序列追加 | 用户行为事件  | Redis algo:user:behavior_seq:* | P0     |
| 新游戏统计更新   | 曝光/点击事件 | Redis algo:newgame:stats:*     | P1     |

---

## 八、附录

### 8.1 编码映射表（需大数据工程师维护）

| 编码类型    | 说明       | 示例                                       |
| ----------- | ---------- | ------------------------------------------ |
| category_id | 游戏类目   | 1-slots, 2-crash, 3-live, 4-virtual        |
| provider_id | 游戏提供商 | 1-pragmatic, 2-evolution, ...              |
| theme_id    | 游戏主题   | 1-egypt, 2-fruit, 3-asian, ...             |
| feature_id  | 游戏特性   | 1-megaways, 2-free_spins, 3-bonus_buy, ... |
| channel_id  | 注册渠道   | 1-organic, 2-facebook, 3-google, ...       |

### 8.2 特征版本管理

- 每次特征逻辑变更需更新 `feature_version` 字段
- A/B测试时可通过版本区分不同特征计算逻辑
- 版本格式：`v{major}.{minor}`，如 `v1.0`, `v1.1`, `v2.0`
