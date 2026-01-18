# Kessbet Casino 游戏数据库结构分析报告

> 文档版本：v1.0  
> 分析日期：2026-01-18  
> 数据来源：docs/game_data.md

---

## 目录

1. [数据库表概览与分类](#一数据库表概览与分类)
2. [数据表详细结构分析](#二数据表详细结构分析)
3. [表间关联关系分析](#三表间关联关系分析)
4. [数据质量评估](#四数据质量评估)
5. [推荐系统相关性分析](#五推荐系统相关性分析)
6. [SQL 查询示例](#六sql-查询示例带详细注释)
7. [总结与建议](#七总结与建议)

---

## 一、数据库表概览与分类

### 1.1 数据库环境信息

| 项目 | 值 |
|------|-----|
| 数据库类型 | MySQL 8.0.32 |
| 服务器地址 | 14.103.211.236:3306 |
| 数据库 Schema | `jdd_aha_ots` (订单数据)、`jdd_aha_config` (配置数据) |

### 1.2 表分类汇总

根据文档分析，识别出以下 **5 个核心业务表**：

| 表名 | 所属 Schema | 类型 | 功能模块 | 重要程度 |
|------|-------------|------|----------|----------|
| `overseas_order_game` | jdd_aha_ots | 核心业务表 | 订单模块 | ⭐⭐⭐⭐⭐ 最高 |
| `overseas_order_detail_game` | jdd_aha_ots | 核心业务表 | 订单明细模块 | ⭐⭐⭐⭐⭐ 最高 |
| `overseas_order_detail_casino` | jdd_aha_ots | 核心业务表 | Casino订单明细 | ⭐⭐⭐⭐ 高 |
| `overseas_casino_game` | jdd_aha_config | 配置表 | 游戏配置模块 | ⭐⭐⭐⭐⭐ 最高 |
| `overseas_category` | jdd_aha_config | 配置表 | 分类配置模块 | ⭐⭐⭐ 中 |

### 1.3 功能模块分组

```
┌─────────────────────────────────────────────────────────────────┐
│                    Kessbet Casino 数据模型                       │
├─────────────────────────────────────────────────────────────────┤
│  【订单模块】                                                    │
│   ├── overseas_order_game (主订单表)                            │
│   ├── overseas_order_detail_game (游戏订单明细)                  │
│   └── overseas_order_detail_casino (Casino订单明细)              │
│                                                                  │
│  【游戏配置模块】                                                 │
│   └── overseas_casino_game (游戏元数据配置表)                    │
│                                                                  │
│  【运营配置模块】                                                 │
│   └── overseas_category (分类配置/Tab配置)                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、数据表详细结构分析

### 2.1 overseas_order_game（游戏订单主表）

**业务用途**：存储用户游戏投注的主订单信息，是整个游戏业务的核心交易表。  
**重要程度**：⭐⭐⭐⭐⭐ 最高（核心业务表）  
**分区策略**：按 `n_user_id` HASH 分区，共 100 个分区

| 字段名 | 数据类型 | 允许NULL | 默认值 | 中文说明 | 业务重要性 | 索引类型 | 备注 |
|--------|----------|----------|--------|----------|------------|----------|------|
| `n_id` | bigint | ❌ | - | 订单唯一标识ID | 高 | 主键(联合) | 雪花算法生成 |
| `n_user_id` | bigint | ❌ | - | 用户ID | 高 | 主键(联合)/普通索引 | 用于分区、关联用户 |
| `s_tenant_code` | varchar(50) | ✅ | NULL | 租户代码 | 中 | - | 多租户标识 |
| `s_biz_type` | varchar(100) | ✅ | NULL | 订单业务类型 | 中 | - | 枚举: `0`=普通下单, `1`=jackpot |
| `s_custom_code` | varchar(50) | ✅ | NULL | 订单简化码 | 低 | 唯一索引 | 用于快速查询的短码 |
| `n_order_money` | decimal(20,4) | ✅ | 0.0000 | 订单金额 | 高 | - | 用户投注总金额 |
| `n_order_pay_money` | decimal(20,4) | ✅ | 0.0000 | 订单实付金额 | 高 | - | 扣除优惠后的实际支付金额 |
| `n_total_reduce_money` | decimal(20,4) | ✅ | 0.0000 | 优惠金额 | 中 | - | 红包/优惠券抵扣金额 |
| `n_total_bonus_money` | decimal(20,2) | ✅ | 0.00 | 加奖金额(扣税后) | 中 | - | ⚠️精度比其他金额字段少2位 |
| `n_actual_win_money` | decimal(20,4) | ✅ | NULL | 实际赢取金额 | 高 | - | 用户最终获奖金额 |
| `n_actual_win_sub_tax_money` | decimal(20,4) | ✅ | NULL | 实际获奖金额(扣税后) | 高 | - | 税后金额 |
| `n_pay_status` | int unsigned | ❌ | 0 | 支付状态 | 高 | - | 枚举: `0`=未支付, `1`=已支付 |
| `n_refund_status` | int | ✅ | 0 | 退款状态 | 高 | - | 枚举: `-2`=等待取消, `-1`=取消失败, `0`=未退款, `1`=用户取消, `2`=系统取消, `3`=系统取消不提交雷达 |
| `n_status` | int | ✅ | 1 | 订单状态 | 高 | - | 枚举: `0`=无效, `1`=有效 |
| `n_open_status` | int | ✅ | 0 | 开奖状态 | 高 | - | 枚举: `0`=未开奖, `1`=部分开奖, `2`=全部开奖 |
| `n_win_status` | int | ✅ | 0 | 赛果状态 | 高 | - | 枚举: `-1`=未有赛果, `0`=不中, `1`=中奖 |
| `n_opt_status` | int | ✅ | 4 | 订单操作状态 | 高 | - | 枚举: `-1`=等待受注, `0`=过关未中奖, `1`=过关中奖, `2`=用户退单, `3`=系统退单, `4`=待开奖, `5`=cashout, `6`=void, `7`=no result, `8`=cancel waiting, `9`=cashout waiting, `10`=取消订单失败, `11`=cashout失败, `12`=输半退费, `13`=系统退单不提交雷达 |
| `d_open_time` | bigint | ✅ | NULL | 开奖时间 | 中 | - | 毫秒级时间戳 |
| `d_buy_time` | bigint | ✅ | NULL | 购买时间 | 高 | - | 毫秒级时间戳，用户下单时间 |
| `d_create_time` | bigint | ✅ | NULL | 创建时间 | 中 | 降序索引 | 毫秒级时间戳 |
| `d_update_time` | bigint | ✅ | NULL | 更新时间 | 低 | - | 毫秒级时间戳 |
| `s_entrance_code` | varchar(50) | ✅ | NULL | 渠道号 | 中 | - | 用户来源渠道标识 |
| `s_ipaddress` | varchar(100) | ✅ | NULL | IP地址 | 低 | - | 订单发起IP地址 |
| `s_uuid` | varchar(100) | ✅ | NULL | 设备号 | 中 | - | 订单发起设备标识 |
| `s_app_version` | varchar(100) | ✅ | NULL | APP版本号 | 低 | - | 订单发起App版本 |
| `s_platform_code` | varchar(100) | ✅ | NULL | 平台代码 | 中 | - | 订单发起平台标识 |

---

### 2.2 overseas_order_detail_game（游戏订单明细表）

**业务用途**：存储每笔游戏订单的详细信息，包括游戏轮次、奖金、供应商等信息。
**重要程度**：⭐⭐⭐⭐⭐ 最高（核心业务表）

| 字段名 | 数据类型 | 允许NULL | 默认值 | 中文说明 | 业务重要性 | 索引类型 | 备注 |
|--------|----------|----------|--------|----------|------------|----------|------|
| `n_id` | bigint | ❌ | - | 明细记录唯一ID | 高 | 主键 | - |
| `n_order_id` | bigint | ✅ | NULL | 关联订单ID | 高 | - | 外键关联 overseas_order_game.n_id ⚠️缺失外键约束 |
| `n_user_id` | bigint | ✅ | NULL | 用户ID | 高 | 联合唯一索引 | - |
| `s_game_id` | varchar(200) | ✅ | '' | 游戏ID | 高 | - | 关联 overseas_casino_game.s_game_id |
| `n_round_id` | bigint | ✅ | NULL | 游戏轮次ID | 中 | - | 单次游戏会话标识 |
| `n_campaign_id` | bigint | ✅ | NULL | 活动ID | 中 | - | 参与的促销活动 |
| `s_campaign_type` | varchar(255) | ✅ | NULL | 活动类型 | 低 | - | 促销活动类型 |
| `n_promo_win_amount` | decimal(20,6) | ✅ | NULL | 促销赢取金额 | 中 | - | 精度较高(6位小数) |
| `s_promo_win_reference` | varchar(200) | ✅ | NULL | 促销赢取引用 | 低 | - | 需要进一步确认含义 |
| `s_result_reference` | varchar(200) | ✅ | NULL | 结果引用 | 低 | - | 需要进一步确认含义 |
| `s_reference` | varchar(200) | ✅ | '' | 交易引用号 | 高 | 联合唯一索引 | 第三方交易流水号 |
| `d_timestamp` | bigint | ✅ | NULL | 时间戳 | 中 | - | 毫秒级时间戳 |
| `s_round_details` | varchar(4000) | ✅ | '' | 轮次详情 | 中 | - | JSON格式的详细信息 |
| `s_bonus_code` | varchar(300) | ✅ | '' | 奖金代码 | 中 | - | 红包/优惠券代码 |
| `s_request_id` | varchar(300) | ✅ | NULL | 请求ID | 低 | - | API请求唯一标识 |
| `s_provider` | varchar(50) | ✅ | '' | 游戏供应商 | 高 | - | 如: Pragmatic Play, Evolution等 |
| `d_create_time` | bigint | ✅ | 0 | 创建时间 | 中 | - | 毫秒级时间戳 |
| `d_update_time` | bigint | ✅ | 0 | 更新时间 | 低 | - | 毫秒级时间戳 |
| `n_jackpot_id` | bigint | ✅ | NULL | Jackpot ID | 中 | - | 关联彩池活动 |
| `s_adjust_reference` | varchar(200) | ✅ | NULL | 调账引用 | 低 | - | 调账操作的关联ID |

---

### 2.3 overseas_order_detail_casino（Casino订单明细表）

**业务用途**：存储特定Casino供应商（如SP供应商）的订单交易明细。
**重要程度**：⭐⭐⭐⭐ 高（核心业务表）

| 字段名 | 数据类型 | 允许NULL | 默认值 | 中文说明 | 业务重要性 | 索引类型 | 备注 |
|--------|----------|----------|--------|----------|------------|----------|------|
| `n_id` | bigint | ❌ | - | 明细记录唯一ID | 高 | 主键 | - |
| `n_order_id` | bigint | ✅ | NULL | 关联订单ID | 高 | - | 外键关联 overseas_order_game.n_id |
| `n_user_id` | bigint | ✅ | NULL | 用户ID | 高 | 联合索引 | - |
| `s_withdraw_trans_id` | varchar(200) | ✅ | '' | 提现交易ID | 中 | - | 提现类操作的流水号 |
| `s_deposit_trans_id` | varchar(200) | ✅ | '' | 充值交易ID | 中 | - | 充值类操作的流水号 |
| `s_rollback_trans_id` | varchar(200) | ✅ | '' | 回滚交易ID | 中 | - | 回滚操作的流水号 |
| `s_type` | varchar(20) | ✅ | '' | 游戏类型/游戏名 | 高 | - | 实际存储游戏名称 |
| `s_action` | varchar(20) | ✅ | '' | 操作类型 | 中 | - | 如: bet, win, refund等 |
| `s_action_id` | varchar(500) | ✅ | '' | 操作ID | 高 | 联合索引 | 唯一操作标识 |
| `s_provider` | varchar(20) | ✅ | '' | 游戏供应商 | 高 | - | 如: SP等 |
| `d_create_time` | bigint | ✅ | 0 | 创建时间 | 中 | - | 毫秒级时间戳 |
| `d_update_time` | bigint | ✅ | 0 | 更新时间 | 低 | - | 毫秒级时间戳 |

---

### 2.4 overseas_casino_game（游戏配置表）

**业务用途**：存储所有Casino游戏的元数据和配置信息，是游戏推荐的核心数据源。
**重要程度**：⭐⭐⭐⭐⭐ 最高（核心配置表）

| 字段名 | 数据类型 | 允许NULL | 默认值 | 中文说明 | 业务重要性 | 索引类型 | 备注 |
|--------|----------|----------|--------|----------|------------|----------|------|
| `n_id` | int | ❌ | AUTO_INCREMENT | 自增主键ID | 中 | 主键 | 自增至614 |
| `s_game_id` | varchar(100) | ✅ | NULL | 游戏唯一标识ID | 高 | 唯一索引 | 第三方游戏ID，推荐系统核心字段 |
| `s_game_name` | varchar(100) | ✅ | NULL | 游戏名称 | 高 | - | 推荐展示字段 |
| `s_game_type_id` | varchar(20) | ✅ | NULL | 游戏类型ID | 高 | - | 游戏分类标识 |
| `s_type_description` | varchar(100) | ✅ | NULL | 类型描述 | 中 | - | 游戏类型的文字说明 |
| `s_technology` | varchar(30) | ✅ | NULL | 技术类型 | 低 | - | 如: HTML5, Flash等 |
| `s_technology_id` | varchar(10) | ✅ | NULL | 技术类型ID | 低 | - | - |
| `s_paltform` | varchar(30) | ✅ | NULL | 支持平台 | 中 | - | ⚠️字段名拼写错误(platform) |
| `n_demo_game_available` | int | ✅ | NULL | 是否支持试玩 | 中 | - | 枚举: 0/1 |
| `s_aspect_ratio` | varchar(20) | ✅ | NULL | 屏幕宽高比 | 低 | - | 如: 16:9, 4:3等 |
| `n_game_id_numeric` | bigint | ✅ | NULL | 游戏数字ID | 低 | - | 冗余字段，与s_game_id重复⚠️ |
| `s_jurisdictions` | varchar(500) | ✅ | NULL | 支持的司法管辖区 | 中 | - | 逗号分隔的地区列表 |
| `s_currencies` | varchar(500) | ✅ | NULL | 支持的货币 | 中 | - | 逗号分隔的货币列表 |
| `n_frb_available` | int | ✅ | 0 | 是否支持免费旋转 | 中 | - | 枚举: 0/1，Free Spin功能 |
| `n_variable_frb_available` | int | ✅ | NULL | 是否支持可变免费旋转 | 低 | - | 高级免费旋转功能 |
| `n_lines` | int | ✅ | NULL | 游戏线数 | 中 | - | 老虎机的支付线数量 |
| `s_features` | varchar(500) | ✅ | NULL | 游戏特性 | 中 | - | JSON/逗号分隔的特性列表 |
| `s_data_type` | varchar(20) | ✅ | NULL | 游戏组合类型 | 高 | - | 枚举: `RNG`=老虎机/视频老虎机, `LC`=真人娱乐场, `VSB`=虚拟体育博彩 |
| `n_category` | int | ✅ | NULL | 游戏类别标签 | 高 | - | 枚举: `1`=新游戏, `2`=热门, `3`=新且热门, `4`=其他 |
| `n_type` | int | ✅ | NULL | 游戏分类ID | 高 | - | 关联 overseas_category 表 |
| `n_sort` | int | ✅ | NULL | 排序值 | 中 | - | 展示排序权重 |
| `n_status` | int | ✅ | NULL | 游戏状态 | 高 | - | 枚举: `0`=禁用, `1`=启用 |
| `d_create_time` | bigint | ✅ | NULL | 创建时间 | 低 | - | 毫秒级时间戳 |
| `d_update_time` | bigint | ✅ | NULL | 更新时间 | 低 | - | 毫秒级时间戳 |
| `s_agent_code` | varchar(20) | ✅ | NULL | 代理商代码 | 低 | - | 游戏供应商标识 |
| `s_img_url` | varchar(100) | ✅ | NULL | 游戏图片URL | 中 | - | 游戏封面图片 |
| `s_start_url` | varchar(500) | ✅ | NULL | 游戏启动URL | 中 | - | 游戏登录/启动链接 |
| `n_hit_rate` | decimal(20,6) | ✅ | NULL | 命中率/返奖率 | 高 | - | 游戏RTP(Return to Player)，推荐系统关键字段 |

---

### 2.5 overseas_category（分类配置表）

**业务用途**：存储所有运营类Tab配置，包括游戏分类、页面配置等。
**重要程度**：⭐⭐⭐ 中（辅助配置表）

| 字段名 | 数据类型 | 允许NULL | 默认值 | 中文说明 | 业务重要性 | 索引类型 | 备注 |
|--------|----------|----------|--------|----------|------------|----------|------|
| `n_id` | int | ❌ | AUTO_INCREMENT | 自增主键ID | 高 | 主键 | - |
| `n_page_id` | int | ✅ | NULL | 所属页面ID | 高 | 普通索引 | 页面标识，`3`=游戏页面 |
| `n_parent_id` | int | ✅ | 0 | 父级分类ID | 中 | 普通索引 | 支持树形结构 |
| `s_name` | varchar(50) | ✅ | '' | 分类名称 | 高 | - | 游戏分类名称 |
| `s_img_url` | varchar(100) | ✅ | NULL | 分类图片URL | 低 | - | 分类图标 |
| `s_value` | varchar(500) | ✅ | NULL | 内部配置值 | 高 | - | JSON格式，如`{"type":1}` |
| `s_config_value` | varchar(1000) | ✅ | NULL | 扩展配置JSON | 中 | - | 各种复杂配置 |
| `s_type_code` | varchar(50) | ✅ | NULL | Tab类型代码 | 中 | - | 分类类型标识 |
| `n_status` | int | ✅ | 1 | 状态 | 高 | - | 枚举: `0`=禁用, `1`=启用 |
| `n_depth` | int | ✅ | 0 | 层级深度 | 低 | - | 树形结构深度 |
| `n_sort` | int | ✅ | 1 | 排序值 | 中 | - | 展示排序 |
| `d_create_time` | datetime | ✅ | CURRENT_TIMESTAMP | 创建时间 | 低 | - | ⚠️标准datetime格式，与其他表不一致 |
| `d_update_time` | datetime | ✅ | NULL | 更新时间 | 低 | - | 标准datetime格式 |
| `s_operator` | varchar(100) | ✅ | '' | 操作者 | 低 | - | 操作人员标识 |
| `n_platform_code` | int | ✅ | 1 | 渠道编码 | 高 | - | 枚举: `1`=H5, `2`=Android, `3`=iOS |
| `s_filter_value` | varchar(500) | ✅ | `{"loginState":0,"versionRange":"-"}` | 过滤字段 | 中 | - | JSON格式，登录状态/版本过滤 |
| `s_expression` | varchar(1000) | ✅ | NULL | 标签过滤表达式 | 低 | - | 需要进一步确认用途 |
| `s_filter_expression` | varchar(1000) | ✅ | NULL | 过滤条件表达式 | 低 | - | 需要进一步确认用途 |

---

## 三、表间关联关系分析

### 3.1 关联关系图

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                              表间关联关系图                                      │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│   overseas_order_game (主订单表)                                               │
│        │                                                                       │
│        │ n_id ──────────────┬───────────────────┐                             │
│        │                    │                   │                             │
│        ▼                    ▼                   ▼                             │
│   overseas_order_detail_game    overseas_order_detail_casino                  │
│   (游戏订单明细)                 (Casino订单明细)                               │
│        │                                                                       │
│        │ s_game_id                                                            │
│        │                                                                       │
│        ▼                                                                       │
│   overseas_casino_game (游戏配置表)                                            │
│        │                                                                       │
│        │ n_type                                                               │
│        │                                                                       │
│        ▼                                                                       │
│   overseas_category (分类配置表)                                               │
│   [n_page_id=3, s_value.type]                                                 │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 关联关系说明

| 关联名称 | 主表 | 从表 | 关联字段 | 关联类型 | 业务说明 |
|----------|------|------|----------|----------|----------|
| 订单-游戏明细 | overseas_order_game | overseas_order_detail_game | n_id → n_order_id | 1:N | 一个订单可能有多条游戏明细 |
| 订单-Casino明细 | overseas_order_game | overseas_order_detail_casino | n_id → n_order_id | 1:N | 一个订单可能有多条Casino明细 |
| 游戏明细-游戏配置 | overseas_order_detail_game | overseas_casino_game | s_game_id → s_game_id | N:1 | 明细关联游戏元数据 |
| 游戏配置-分类 | overseas_casino_game | overseas_category | n_type → JSON(s_value.type) | N:1 | 游戏关联分类（非标准关联⚠️） |

### 3.3 数据一致性约束问题 ⚠️

1. **缺失外键约束**：所有表间关联都没有定义物理外键约束，仅依赖业务逻辑保证一致性
2. **非标准关联**：`overseas_casino_game.n_type` 与 `overseas_category` 的关联通过 JSON 字段 `s_value` 解析实现，增加查询复杂度
3. **分区表限制**：`overseas_order_game` 使用 HASH 分区，可能影响跨分区查询性能

---

## 四、数据质量评估

### 4.1 数据缺失问题

| 表名 | 字段 | 缺失情况 | 影响程度 | 建议处理方式 |
|------|------|----------|----------|--------------|
| overseas_order_detail_game | s_game_id → s_game_name | 存在游戏ID找不到游戏名称的情况（SQL注释已说明） | 高 | 补全游戏配置数据或建立数据同步机制 |
| overseas_order_detail_casino | s_type | 用游戏名代替分类名（SP供应商未提供分类） | 中 | 需与供应商协商获取分类数据 |
| overseas_casino_game | 多个字段 | 允许NULL较多，可能存在不完整记录 | 中 | 设置合理默认值 |

### 4.2 冗余与重复字段

| 表名 | 字段 | 问题描述 | 建议 |
|------|------|----------|------|
| overseas_casino_game | n_game_id_numeric | 与 s_game_id 功能重复 | 评估后可删除 |
| overseas_casino_game | s_technology_id + s_technology | 数据冗余 | 保留一个即可 |
| overseas_order_game | n_open_status + n_opt_status | 状态枚举含义有重叠 | 需梳理状态机 |

### 4.3 数据一致性问题

| 问题类型 | 具体描述 | 影响 |
|----------|----------|------|
| 时间字段格式不一致 | `overseas_category` 使用 datetime，其他表使用 bigint 时间戳 | 查询时需转换 |
| 金额精度不一致 | `n_total_bonus_money` 使用 decimal(20,2)，其他金额使用 decimal(20,4) | 计算时可能精度丢失 |
| 字段命名拼写错误 | `s_paltform` 应为 `s_platform` | 代码可读性差 |
| 用户ID范围 | SQL中使用 `n_user_id > 1100000` 过滤测试数据 | 需确认正式用户ID起始值 |

### 4.4 测试数据识别

根据 SQL 查询示例，发现以下测试数据特征：
- 用户ID小于 1100000 的可能是测试用户
- 时间过滤条件 `d_create_time >= UNIX_TIMESTAMP('2025-12-31')` 用于排除历史测试数据

---

## 五、推荐系统相关性分析

### 5.1 推荐系统核心字段标注

#### 🔴 用户行为特征（User Behavior Features）

| 表名 | 字段 | 用途 | 推荐算法应用 |
|------|------|------|--------------|
| overseas_order_game | n_user_id | 用户唯一标识 | 用户画像构建 |
| overseas_order_game | n_order_money | 投注金额 | 用户消费能力特征 |
| overseas_order_game | n_order_pay_money | 实际支付金额 | 用户真实消费行为 |
| overseas_order_game | n_actual_win_money | 赢取金额 | 用户盈亏计算、风险偏好 |
| overseas_order_game | d_buy_time | 购买时间 | 用户活跃时段分析 |
| overseas_order_game | n_win_status | 中奖状态 | 用户中奖率计算 |
| overseas_order_game | s_platform_code | 平台代码 | 用户设备偏好 |
| overseas_order_detail_game | s_game_id | 游戏ID | 用户游戏偏好（核心） |
| overseas_order_detail_game | s_provider | 游戏供应商 | 用户供应商偏好 |
| overseas_order_detail_game | n_round_id | 游戏轮次 | 用户游戏深度/频次 |

#### 🟢 游戏属性特征（Item Features）

| 表名 | 字段 | 用途 | 推荐算法应用 |
|------|------|------|--------------|
| overseas_casino_game | s_game_id | 游戏唯一标识 | Item ID |
| overseas_casino_game | s_game_name | 游戏名称 | 展示 & 文本特征 |
| overseas_casino_game | n_category | 游戏类别 | 分类推荐（新游戏/热门） |
| overseas_casino_game | n_type | 游戏分类ID | 基于内容的推荐 |
| overseas_casino_game | s_data_type | 游戏组合类型 | RNG/LC/VSB分类推荐 |
| overseas_casino_game | n_hit_rate | 命中率/RTP | 用户风险偏好匹配 |
| overseas_casino_game | s_features | 游戏特性 | 基于特性的推荐 |
| overseas_casino_game | n_frb_available | 免费旋转支持 | 促销活动匹配 |
| overseas_casino_game | n_lines | 游戏线数 | 老虎机复杂度特征 |
| overseas_casino_game | n_sort | 排序权重 | 热度/运营权重 |
| overseas_casino_game | n_status | 游戏状态 | 过滤不可用游戏 |

#### 🔵 上下文特征（Context Features）

| 表名 | 字段 | 用途 | 推荐算法应用 |
|------|------|------|--------------|
| overseas_order_game | s_platform_code | 平台代码 | 设备上下文 |
| overseas_order_game | s_entrance_code | 渠道号 | 来源渠道上下文 |
| overseas_order_game | s_app_version | APP版本 | 版本兼容性 |
| overseas_category | n_platform_code | 渠道编码 | 多端适配 |
| overseas_casino_game | s_currencies | 支持货币 | 地区/货币上下文 |
| overseas_casino_game | s_jurisdictions | 司法管辖区 | 地区合规性过滤 |

### 5.2 推荐系统可构建的特征

```
┌─────────────────────────────────────────────────────────────────┐
│                    可构建的推荐特征                               │
├─────────────────────────────────────────────────────────────────┤
│  【用户特征】                                                    │
│   ├── 投注金额分布（低/中/高端用户）                              │
│   ├── 游戏偏好（基于历史游戏分布）                                │
│   ├── 供应商偏好（基于历史供应商分布）                            │
│   ├── 活跃时段（基于 d_buy_time 分析）                           │
│   ├── 中奖率（n_win_status 统计）                                │
│   ├── 风险偏好（高RTP vs 低RTP游戏选择）                         │
│   └── 设备偏好（H5/Android/iOS）                                 │
│                                                                  │
│  【游戏特征】                                                    │
│   ├── 游戏类型（RNG/LC/VSB）                                     │
│   ├── 游戏分类（n_type + overseas_category）                     │
│   ├── 热度标签（n_category: 新/热/新且热）                        │
│   ├── RTP水平（n_hit_rate）                                      │
│   ├── 游戏复杂度（n_lines）                                      │
│   └── 促销适配（n_frb_available）                                │
│                                                                  │
│  【交互特征】                                                    │
│   ├── 用户-游戏互动矩阵（协同过滤）                               │
│   ├── 游戏序列（基于时间的游戏切换模式）                          │
│   └── 投注-赢取比（用户盈亏趋势）                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 数据结构与推荐系统设计的差异分析

基于文档分析，发现以下潜在问题：

| 问题 | 描述 | 建议 |
|------|------|------|
| 缺少用户画像表 | 当前数据需要从订单表实时聚合 | 建议增加用户特征预计算表 |
| 缺少游戏特征向量 | s_features 是文本格式，不适合向量计算 | 建议提取为结构化特征表 |
| 缺少游戏统计表 | 游戏热度、点击量等需实时计算 | 建议增加游戏统计预聚合表 |
| 缺少推荐日志表 | 无法追踪推荐效果 | 建议增加推荐曝光/点击日志表 |
| 分类关联复杂 | 游戏分类需通过JSON解析关联 | 建议优化为直接外键关联 |

---

## 六、SQL 查询示例（带详细注释）

```sql
-- ===============================================================
-- 游戏投注行为特征数据提取 SQL
-- 用途：为推荐系统构建用户行为特征数据集
-- 数据范围：2025-12-31 之后的有效订单数据
-- ===============================================================

-- CTE 1: 提取主订单信息
WITH order_info AS (
    SELECT
        n_id,                    -- 订单唯一ID，用于关联明细表
        n_user_id,               -- 用户ID，推荐系统核心用户标识
        s_platform_code,         -- 平台代码（H5/Android/iOS），用于上下文特征
        s_app_version,           -- APP版本号，用于版本兼容性分析
        s_uuid,                  -- 设备UUID，用于设备去重和跨设备追踪
        s_ipaddress,             -- IP地址，用于地理位置分析（需IP解析）
        d_buy_time,              -- 购买时间戳，用于时序分析和活跃时段统计
        n_status,                -- 订单状态（0=无效,1=有效），需过滤无效订单
        n_pay_status,            -- 支付状态（0=未支付,1=已支付），核心业务字段
        n_actual_win_money,      -- 实际赢取金额，用于计算用户盈亏
        n_total_bonus_money,     -- 加奖金额（税后），用于分析促销效果
        n_order_money,           -- 订单金额，用户投注金额特征
        n_order_pay_money        -- 实际支付金额，扣除优惠后的真实消费
    FROM
        jdd_aha_ots.overseas_order_game
    WHERE
        -- 时间过滤：只取2025-12-31之后的数据，排除历史测试数据
        d_create_time >= UNIX_TIMESTAMP(CAST('2025-12-31' AS DATETIME)) * 1000
),

-- CTE 2: 整合游戏订单明细与游戏配置
-- 包含两个数据源：overseas_order_detail_game + overseas_order_detail_casino
order_game_detail_ex AS (
    -- 来源1: 游戏订单明细表（主要Casino游戏）
    SELECT
        t1.n_order_id,           -- 关联主订单的订单ID
        t1.s_provider,           -- 游戏供应商（如Pragmatic Play, Evolution等）
        t2.s_game_name,          -- 游戏名称，用于展示和文本特征
        t2.s_name                -- 游戏分类名称，用于分类推荐
    FROM
        (
            SELECT
                n_order_id,
                s_game_id,
                s_provider
            FROM
                `jdd_aha_ots`.`overseas_order_detail_game`
            WHERE
                n_user_id > 1100000   -- 过滤测试用户，正式用户ID从1100000开始
        ) t1
    LEFT JOIN
        (
            -- 子查询：关联游戏配置表和分类表获取游戏完整信息
            SELECT
                ocg.s_game_id,        -- 游戏ID，用于关联
                ocg.s_game_name,      -- 游戏名称
                ocg.n_type,           -- 游戏分类ID
                oc.s_name             -- 游戏分类名称
            FROM
                `jdd_aha_config`.`overseas_casino_game` ocg
            LEFT JOIN
                (
                    -- 从分类配置表提取游戏分类信息
                    -- 条件：n_platform_code=1(H5端)，n_page_id=3(游戏页面)
                    SELECT
                        s_name,
                        -- 从JSON字段s_value中提取type值
                        CAST(get_json_object(s_value, '$.type') AS INT) AS extracted_values_types
                    FROM
                        `jdd_aha_config`.`overseas_category`
                    WHERE
                        n_platform_code = 1           -- H5端配置
                        AND n_page_id = 3             -- 游戏页面
                        AND s_value LIKE '{"type":%}' -- 包含type字段的JSON
                ) oc
                ON ocg.n_type = oc.extracted_values_types
        ) t2
        ON t1.s_game_id = t2.s_game_id
    WHERE
        s_game_name IS NOT NULL   -- ⚠️ 数据质量问题：存在游戏ID找不到游戏名称的情况
        AND d_create_time >= UNIX_TIMESTAMP(CAST('2025-12-31' AS DATETIME)) * 1000

    UNION

    -- 来源2: Casino订单明细表（SP供应商等特殊游戏）
    SELECT
        n_order_id,
        s_provider,               -- 游戏供应商
        s_type AS s_game_name,    -- ⚠️ SP供应商：用s_type作为游戏名
        s_type AS s_name          -- ⚠️ SP供应商：未提供分类，用游戏名替代
    FROM
        `jdd_aha_ots`.`overseas_order_detail_casino`
    WHERE
        n_user_id > 1100000       -- 过滤测试用户
        AND d_create_time >= UNIX_TIMESTAMP(CAST('2025-12-31' AS DATETIME)) * 1000
)

-- 主查询：整合订单信息和游戏明细
SELECT
    o.n_id,                      -- 订单ID
    o.n_user_id,                 -- 用户ID
    o.s_platform_code,           -- 平台代码
    o.s_app_version,             -- APP版本
    o.s_uuid,                    -- 设备UUID
    o.s_ipaddress,               -- IP地址
    o.d_buy_time,                -- 购买时间
    o.n_status,                  -- 订单状态
    o.n_pay_status,              -- 支付状态
    o.n_actual_win_money,        -- 实际赢取金额
    o.n_order_money,             -- 订单金额
    o.n_order_pay_money,         -- 实际支付金额

    g.s_provider,                -- 游戏供应商
    g.s_name,                    -- 游戏分类名
    g.s_game_name                -- 游戏名称

    -- TODO: 待补充字段（原SQL中注释标注）
    -- ,订单是否有被rollback  1 有，0 无
    -- ,使用的红包的类型

FROM
    order_info o
LEFT JOIN
    order_game_detail_ex g
    ON o.n_id = g.n_order_id;
```

---

## 七、总结与建议

### 7.1 当前数据结构评估

| 评估维度 | 评分 | 说明 |
|----------|------|------|
| 数据完整性 | ⭐⭐⭐ | 存在游戏ID无法关联游戏名的情况 |
| 字段规范性 | ⭐⭐⭐ | 有拼写错误和类型不一致 |
| 关联关系 | ⭐⭐ | 缺少外键约束，非标准JSON关联 |
| 推荐系统适配度 | ⭐⭐⭐ | 基础数据充足，但缺少预聚合表 |
| 时间字段一致性 | ⭐⭐ | datetime与bigint混用 |

### 7.2 推荐系统建设建议

1. **新增用户特征预聚合表**：定期计算用户投注偏好、活跃时段等特征
2. **新增游戏统计表**：存储游戏热度、点击量、转化率等指标
3. **新增推荐日志表**：记录推荐曝光和点击，用于A/B测试和模型优化
4. **优化游戏分类关联**：将JSON解析改为直接外键关联
5. **建立数据同步机制**：确保游戏配置表与订单明细表的一致性

### 7.3 数据治理优先级

| 优先级 | 任务 | 预期收益 |
|--------|------|----------|
| P0 | 补全游戏配置数据缺失 | 提高数据关联成功率 |
| P0 | 统一时间字段格式 | 简化查询和ETL |
| P1 | 修正字段拼写错误 | 提高代码可读性 |
| P1 | 新增推荐相关预聚合表 | 支撑推荐系统建设 |
| P2 | 优化分类关联方式 | 提升查询性能 |
| P2 | 添加物理外键约束 | 保证数据一致性 |

---

## 附录：字段命名规范

根据现有表结构分析，Kessbet 使用以下命名规范：

| 前缀 | 含义 | 示例 |
|------|------|------|
| `n_` | 数值类型字段 | n_id, n_user_id, n_status |
| `s_` | 字符串类型字段 | s_game_id, s_game_name |
| `d_` | 日期/时间类型字段 | d_create_time, d_buy_time |

---


