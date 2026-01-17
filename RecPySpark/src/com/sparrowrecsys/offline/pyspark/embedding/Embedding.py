"""
=====================================================================================
Embedding.py - 推荐系统中的嵌入向量 (Embedding) 生成模块

本模块实现了推荐系统中常用的几种 Embedding 技术:
1. Item2Vec: 借鉴 Word2Vec 的思想，将用户的观影序列视为"句子"，电影ID视为"单词"，
             从而学习电影的低维稠密向量表示
2. Graph Embedding: 基于物品转移图，通过随机游走(Random Walk)生成序列，再用Word2Vec训练
3. User Embedding: 通过聚合用户观看过的电影的Embedding来生成用户Embedding
4. LSH (局部敏感哈希): 用于高效地进行近似最近邻搜索

核心原理:
- Word2Vec 的核心思想是"相似的词出现在相似的上下文中"
- 在推荐场景中，如果两个物品经常被同一用户连续观看，它们可能具有相似性
- 通过学习物品的Embedding向量，可以用向量距离来衡量物品相似度
=====================================================================================
"""

import os

# 设置 PySpark 使用的 Python 解释器，确保 driver 和 worker 使用相同版本
os.environ['PYSPARK_PYTHON'] = '/opt/anaconda3/envs/sparrow/bin/python'
os.environ['PYSPARK_DRIVER_PYTHON'] = '/opt/anaconda3/envs/sparrow/bin/python'

from pyspark import SparkConf
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.types import *
from pyspark.ml.feature import BucketedRandomProjectionLSH
from pyspark.mllib.feature import Word2Vec
from pyspark.ml.linalg import Vectors
import random
from collections import defaultdict
import numpy as np
from pyspark.sql import functions as F


class UdfFunction:
    """
    自定义 UDF (User Defined Function) 工具类
    用于在 Spark DataFrame 操作中使用自定义的 Python 函数
    """

    @staticmethod
    def sortF(movie_list, timestamp_list):
        """
        根据时间戳对电影列表进行排序，生成按时间顺序排列的观影序列
        
        这个函数的作用是将用户的观影记录按照观看时间排序，
        因为 Embedding 学习需要保持物品的时序关系
        
        参数:
            movie_list: 电影ID列表，例如 [1, 2, 3]
            timestamp_list: 对应的时间戳列表，例如 [1112486027, 1212546032, 1012486033]
        
        返回:
            按时间戳升序排列的电影ID列表
        
        示例:
            输入: movie_list = [1, 2, 3]
                  timestamp_list = [1112486027, 1212546032, 1012486033]
            输出: [3, 1, 2]  
            # 因为时间戳 1012486033 < 1112486027 < 1212546032
            # 所以电影观看顺序是 3 -> 1 -> 2
        """
        # 将电影ID和时间戳打包成元组列表
        pairs = []
        for m, t in zip(movie_list, timestamp_list):
            pairs.append((m, t))
        
        # 按时间戳升序排序 (key=lambda x: x[1] 表示按元组的第二个元素排序)
        pairs = sorted(pairs, key=lambda x: x[1])
        
        # 只返回排序后的电影ID列表
        return [x[0] for x in pairs]


def processItemSequence(spark, rawSampleDataPath):
    """
    处理原始评分数据，生成用户的观影序列
    
    这是 Item2Vec 的数据预处理步骤:
    1. 读取用户评分数据
    2. 筛选高分评分 (>=3.5)，认为这些是用户真正感兴趣的电影
    3. 按用户分组，将每个用户观看的电影按时间排序，形成观影序列
    
    为什么要按时间排序？
    - Word2Vec 学习的是序列中词语的共现关系
    - 在推荐场景中，用户连续观看的电影之间可能存在某种关联
    - 保持时序可以捕捉用户的兴趣演化和物品之间的转移关系
    
    参数:
        spark: SparkSession 实例
        rawSampleDataPath: 原始评分数据文件路径 (CSV格式)
    
    返回:
        RDD，每个元素是一个用户的观影序列列表，如 ['858', '50', '593', '457']
    
    数据流程图:
        原始数据 -> 筛选高分 -> 按用户分组 -> 时间排序 -> 生成序列
        
        ratings.csv                    用户观影序列
        ┌─────────────────────┐        ┌────────────────────────┐
        │userId,movieId,rating│   =>   │['858','50','593','457']│  用户1
        │   timestamp         │        │['1','2','3','4','5']   │  用户2
        └─────────────────────┘        │['10','20','30']        │  用户3
                                       └────────────────────────┘
    """
    # 读取CSV格式的评分数据
    # 数据格式: userId, movieId, rating, timestamp
    ratingSamples = spark.read.format("csv").option("header", "true").load(rawSampleDataPath)
    
    # 注册自定义排序函数为 Spark UDF
    # ArrayType(StringType()) 表示返回值是字符串数组类型
    sortUdf = udf(UdfFunction.sortF, ArrayType(StringType()))
    
    # 数据处理流水线:
    userSeq = ratingSamples \
        .where(F.col("rating") >= 3.5) \
        .groupBy("userId") \
        .agg(sortUdf(F.collect_list("movieId"), F.collect_list("timestamp")).alias('movieIds')) \
        .withColumn("movieIdStr", array_join(F.col("movieIds"), " "))
    # 解释:
    # 1. where(rating >= 3.5): 只保留评分>=3.5的记录，过滤掉用户不感兴趣的电影
    #    注意: CSV 读取的 rating 是字符串类型，Spark 会自动进行类型转换后比较
    # 2. groupBy("userId"): 按用户ID分组
    # 3. collect_list(): 将每个用户的movieId和timestamp收集成列表
    # 4. sortUdf(): 调用自定义函数按时间排序
    # 5. array_join(): 将数组转换为空格分隔的字符串，方便后续处理
    
    # 返回 RDD 格式的观影序列
    # 每个元素是一个列表，如 ['858', '50', '593', '457']
    return userSeq.select('movieIdStr').rdd.map(lambda x: x[0].split(' '))


def embeddingLSH(spark, movieEmbMap):
    """
    使用 LSH (Locality Sensitive Hashing，局部敏感哈希) 对电影 Embedding 进行索引
    
    LSH 原理:
    - 在高维空间中进行精确的最近邻搜索计算量巨大 (O(n) 暴力搜索)
    - LSH 通过设计特殊的哈希函数，使得相似的向量更可能被哈希到同一个桶中
    - 查询时只需在同一个桶内搜索，大大减少计算量
    - 牺牲一定精度换取速度，属于近似最近邻 (ANN) 算法
    
    BucketedRandomProjectionLSH 工作原理:
    1. 随机生成投影向量
    2. 将每个数据点投影到该向量上得到一个标量值
    3. 将标量值除以 bucketLength 并取整，得到桶号
    4. 使用多个哈希表 (numHashTables) 提高召回率
    
    应用场景:
    - 在推荐系统中，当物品数量很大时 (如百万级)
    - 需要快速找到与目标物品相似的候选物品
    - LSH 可以在毫秒级完成近似最近邻搜索
    
    参数:
        spark: SparkSession 实例
        movieEmbMap: 字典，key 是电影ID，value 是 Embedding 向量列表
    """
    # 将字典格式的 Embedding 转换为 DataFrame 格式
    movieEmbSeq = []
    for key, embedding_list in movieEmbMap.items():
        # 确保 Embedding 值是 float64 类型
        embedding_list = [np.float64(embedding) for embedding in embedding_list]
        # 使用 Spark ML 的 Vectors.dense 创建稠密向量
        movieEmbSeq.append((key, Vectors.dense(embedding_list)))
    
    # 创建 DataFrame，列名为 movieId 和 emb
    movieEmbDF = spark.createDataFrame(movieEmbSeq).toDF("movieId", "emb")
    
    # 创建 LSH 模型
    # inputCol: 输入的向量列名
    # outputCol: 输出的桶ID列名
    # bucketLength: 桶的宽度，值越小桶越多，精度越高但速度越慢
    # numHashTables: 哈希表数量，数量越多召回率越高但速度越慢
    bucketProjectionLSH = BucketedRandomProjectionLSH(
        inputCol="emb", 
        outputCol="bucketId", 
        bucketLength=0.1,  # 桶宽度
        numHashTables=3     # 使用3个独立的哈希表
    )
    
    # 训练 LSH 模型 (学习投影向量)
    bucketModel = bucketProjectionLSH.fit(movieEmbDF)
    
    # 对所有电影 Embedding 进行转换，得到桶ID
    embBucketResult = bucketModel.transform(movieEmbDF)
    
    # 打印结果用于调试
    print("movieId, emb, bucketId schema:")
    embBucketResult.printSchema()
    print("movieId, emb, bucketId data result:")
    embBucketResult.show(10, truncate=False)
    
    # 演示近似最近邻搜索
    # 给定一个查询向量，找出最相似的5个电影
    print("Approximately searching for 5 nearest neighbors of the sample embedding:")
    sampleEmb = Vectors.dense(0.795, 0.583, 1.120, 0.850, 0.174, -0.839, -0.0633, 0.249, 0.673, -0.237)
    bucketModel.approxNearestNeighbors(movieEmbDF, sampleEmb, 5).show(truncate=False)


def trainItem2vec(spark, samples, embLength, embOutputPath, saveToRedis, redisKeyPrefix):
    """
    训练 Item2Vec 模型，学习物品的 Embedding 向量
    
    Item2Vec 原理 (基于 Word2Vec):
    ================================
    Word2Vec 是 Google 提出的词向量学习算法，核心思想是:
    "一个词的含义由它周围的词决定" (分布式假设)
    
    Item2Vec 将这个思想应用到推荐场景:
    - 将用户的行为序列 (如观影序列) 视为"句子"
    - 将物品 (如电影) 视为"单词"
    - 如果两个物品经常出现在同一用户的行为序列中，它们就是相似的
    
    Skip-gram 模型 (Word2Vec 的一种实现):
    - 输入: 中心词
    - 输出: 预测周围的上下文词
    - 训练目标: 最大化上下文词出现的概率
    
    示例:
        观影序列: [泰坦尼克号, 罗密欧与朱丽叶, 恋恋笔记本, 怦然心动]
        
        当窗口大小=2，中心词="罗密欧与朱丽叶"时:
        上下文词 = {泰坦尼克号, 恋恋笔记本}
        模型学习: 浪漫电影的 Embedding 彼此接近
    
    参数:
        spark: SparkSession 实例
        samples: RDD，每个元素是一个物品序列列表
        embLength: Embedding 向量的维度 (通常 10-300)
        embOutputPath: Embedding 向量的输出文件路径
        saveToRedis: 是否保存到 Redis (当前未实现)
        redisKeyPrefix: Redis 键前缀
    
    返回:
        训练好的 Word2Vec 模型
    """
    # 创建 Word2Vec 模型并设置参数
    word2vec = Word2Vec() \
        .setVectorSize(embLength) \
        .setWindowSize(5) \
        .setNumIterations(10)
    # 参数说明:
    # - VectorSize: Embedding 向量维度，维度越高表达能力越强，但训练越慢
    # - WindowSize: 上下文窗口大小，决定了考虑多少个相邻物品
    #   例如窗口=5，则考虑中心词前后各5个词作为上下文
    # - NumIterations: 训练迭代次数，次数越多模型越精确
    
    # 训练模型
    # samples 格式: [['858', '50', '593'], ['1', '2', '3'], ...]
    model = word2vec.fit(samples)
    
    # 测试: 找出与电影 "158" 最相似的 20 个电影
    # findSynonyms 使用余弦相似度计算
    synonyms = model.findSynonyms("158", 20)
    for synonym, cosineSimilarity in synonyms:
        print(synonym, cosineSimilarity)
    
    # 保存 Embedding 向量到文件
    # 创建输出目录
    embOutputDir = '/'.join(embOutputPath.split('/')[:-1])
    if not os.path.exists(embOutputDir):
        os.makedirs(embOutputDir)
    
    # 写入文件，格式: movieId:emb1 emb2 emb3 ...
    with open(embOutputPath, 'w') as f:
        for movie_id in model.getVectors():
            vectors = " ".join([str(emb) for emb in model.getVectors()[movie_id]])
            f.write(movie_id + ":" + vectors + "\n")
    
    # 使用 LSH 对 Embedding 建立索引，用于快速相似搜索
    embeddingLSH(spark, model.getVectors())
    
    return model


def generate_pair(x):
    """
    从观影序列中生成相邻物品对
    
    这个函数用于 Graph Embedding 的数据预处理:
    - 将行为序列转换为物品之间的转移关系
    - 每个相邻的物品对代表一次"转移"
    
    参数:
        x: 观影序列列表，如 ['858', '50', '593', '457']
    
    返回:
        相邻物品对列表，如 [('858', '50'), ('50', '593'), ('593', '457')]
    
    图示:
        序列: A -> B -> C -> D
        
        生成的物品对:
        (A, B) - 表示从 A 转移到 B
        (B, C) - 表示从 B 转移到 C
        (C, D) - 表示从 C 转移到 D
    """
    pairSeq = []
    previousItem = ''
    
    for item in x:
        if not previousItem:
            # 第一个物品，还没有前驱，只记录
            previousItem = item
        else:
            # 生成 (前一个物品, 当前物品) 对
            pairSeq.append((previousItem, item))
            previousItem = item
    
    return pairSeq


def generateTransitionMatrix(samples):
    """
    从用户行为序列中生成物品转移矩阵
    
    转移矩阵是 Graph Embedding (图嵌入) 的核心数据结构:
    - 表示从一个物品转移到另一个物品的概率
    - 用于后续的随机游走采样
    
    原理:
    假设用户依次观看了 A -> B -> C，则:
    - P(B|A) 增加: 观看了 A 之后观看 B 的概率增加
    - P(C|B) 增加: 观看了 B 之后观看 C 的概率增加
    
    转移概率的计算:
    P(j|i) = count(i->j) / sum(count(i->k) for all k)
    即: 从 i 转移到 j 的次数 / 从 i 转移出去的总次数
    
    参数:
        samples: RDD，每个元素是一个物品序列
    
    返回:
        transitionMatrix: 转移概率矩阵，transitionMatrix[i][j] = P(j|i)
        itemDistribution: 物品分布，itemDistribution[i] = 物品 i 作为起点的概率
    
    示例:
        用户1序列: A -> B -> C
        用户2序列: A -> B -> D
        用户3序列: B -> C
        
        物品对统计:
        (A, B): 2次
        (B, C): 2次
        (B, D): 1次
        
        转移概率:
        P(B|A) = 2/2 = 1.0  (从A一定转移到B)
        P(C|B) = 2/3 ≈ 0.67
        P(D|B) = 1/3 ≈ 0.33
    """
    # Step 1: 生成所有相邻物品对
    # flatMap 会将每个序列的物品对展开成一个扁平的 RDD
    pairSamples = samples.flatMap(lambda x: generate_pair(x))
    
    # Step 2: 统计每个物品对出现的次数
    # countByValue 返回字典: {(itemA, itemB): count, ...}
    pairCountMap = pairSamples.countByValue()
    
    # Step 3: 构建转移计数矩阵和物品出现次数统计
    pairTotalCount = 0  # 总的物品对数量
    transitionCountMatrix = defaultdict(dict)  # 转移计数矩阵
    itemCountMap = defaultdict(int)  # 每个物品作为起点的次数
    
    for key, cnt in pairCountMap.items():
        key1, key2 = key  # key1 -> key2 的转移
        transitionCountMatrix[key1][key2] = cnt
        itemCountMap[key1] += cnt  # key1 作为起点的总次数
        pairTotalCount += cnt
    
    # Step 4: 将计数转换为概率
    transitionMatrix = defaultdict(dict)
    itemDistribution = defaultdict(dict)
    
    # 计算转移概率: P(key2|key1) = count(key1->key2) / sum(count(key1->*))
    for key1, transitionMap in transitionCountMatrix.items():
        for key2, cnt in transitionMap.items():
            transitionMatrix[key1][key2] = transitionCountMatrix[key1][key2] / itemCountMap[key1]
    
    # 计算物品分布: P(item) = count(item作为起点) / 总转移次数
    for itemid, cnt in itemCountMap.items():
        itemDistribution[itemid] = cnt / pairTotalCount
    
    return transitionMatrix, itemDistribution


def oneRandomWalk(transitionMatrix, itemDistribution, sampleLength):
    """
    执行一次随机游走，生成一条采样序列
    
    随机游走 (Random Walk) 原理:
    ================================
    想象一个人在图上随机行走:
    1. 首先根据物品分布随机选择一个起点
    2. 在每个节点，根据转移概率随机选择下一个要访问的节点
    3. 重复步骤2直到达到指定长度
    
    这样生成的序列保留了图的结构信息:
    - 如果两个节点之间转移概率高，它们更可能在同一条游走路径中相邻出现
    - 将这些序列输入 Word2Vec，可以学习节点的向量表示
    
    与原始序列的区别:
    - 原始序列只使用真实用户行为
    - 随机游走可以生成更多样本，探索更多可能的路径
    - 即使两个物品没有直接共现，如果它们在图中接近，随机游走也可能发现这种关系
    
    参数:
        transitionMatrix: 转移概率矩阵
        itemDistribution: 物品的初始分布 (用于选择起点)
        sampleLength: 游走序列的长度
    
    返回:
        生成的随机游走序列，如 ['A', 'B', 'C', 'D', ...]
    
    图示:
        物品转移图:
            A --0.6--> B
            A --0.4--> C
            B --0.7--> C
            B --0.3--> D
            
        可能的游走路径:
            A -> B -> C (概率: 0.6 * 0.7 = 0.42)
            A -> B -> D (概率: 0.6 * 0.3 = 0.18)
            A -> C      (概率: 0.4)
    """
    sample = []
    
    # ========== Step 1: 根据物品分布随机选择起点 ==========
    # 使用轮盘赌算法 (Roulette Wheel Selection):
    # 生成一个 [0, 1) 的随机数，按照累积概率分布选择物品
    randomDouble = random.random()
    firstItem = ""
    accumulateProb = 0.0
    
    for item, prob in itemDistribution.items():
        accumulateProb += prob
        # 当累积概率超过随机数时，选择当前物品
        # 概率越大的物品，越容易被选中
        if accumulateProb >= randomDouble:
            firstItem = item
            break
    
    sample.append(firstItem)
    curElement = firstItem
    
    # ========== Step 2: 按转移概率进行随机游走 ==========
    i = 1
    while i < sampleLength:
        # 检查当前物品是否有出边 (是否可以继续游走)
        if (curElement not in itemDistribution) or (curElement not in transitionMatrix):
            break  # 当前物品没有后继，终止游走
        
        # 获取从当前物品出发的转移概率分布
        probDistribution = transitionMatrix[curElement]
        
        # 使用轮盘赌算法选择下一个物品
        randomDouble = random.random()
        accumulateProb = 0.0
        
        for item, prob in probDistribution.items():
            accumulateProb += prob
            if accumulateProb >= randomDouble:
                curElement = item
                break
        
        sample.append(curElement)
        i += 1
    
    return sample


def randomWalk(transitionMatrix, itemDistribution, sampleCount, sampleLength):
    """
    批量执行随机游走，生成多条采样序列
    
    为什么需要多次随机游走？
    - 单次游走只能探索图的一小部分
    - 多次游走从不同起点出发，可以更全面地覆盖图结构
    - 更多的样本有助于 Word2Vec 学习更准确的向量表示
    
    参数:
        transitionMatrix: 转移概率矩阵
        itemDistribution: 物品分布
        sampleCount: 游走次数 (生成多少条序列)
        sampleLength: 每条游走序列的长度
    
    返回:
        samples: 所有随机游走序列的列表
    """
    samples = []
    for i in range(sampleCount):
        samples.append(oneRandomWalk(transitionMatrix, itemDistribution, sampleLength))
    return samples


def graphEmb(samples, spark, embLength, embOutputFilename, saveToRedis, redisKeyPrefix):
    """
    Graph Embedding (图嵌入) - DeepWalk 算法实现
    
    DeepWalk 算法流程:
    ================================
    1. 构建物品转移图: 从用户行为序列中提取物品之间的转移关系
    2. 随机游走采样: 在图上进行多次随机游走，生成新的序列
    3. 训练 Word2Vec: 将随机游走序列作为训练数据
    
    与直接用 Item2Vec 的区别:
    - Item2Vec 直接使用原始用户行为序列
    - Graph Embedding 先构建转移图，再通过随机游走生成序列
    - 随机游走可以发现间接关联: 
      即使 A 和 C 没有直接共现，但如果 A->B 和 B->C 的转移概率都很高，
      随机游走可能生成 A->B->C 的序列，从而学习到 A 和 C 的关系
    
    参数:
        samples: 原始用户行为序列 (用于构建转移图)
        spark: SparkSession 实例
        embLength: Embedding 向量维度
        embOutputFilename: 输出文件路径
        saveToRedis: 是否保存到 Redis
        redisKeyPrefix: Redis 键前缀
    """
    # Step 1: 从原始序列构建转移矩阵
    transitionMatrix, itemDistribution = generateTransitionMatrix(samples)
    
    # Step 2: 设置随机游走参数
    sampleCount = 20000   # 生成 20000 条随机游走序列
    sampleLength = 10     # 每条序列长度为 10
    
    # Step 3: 执行随机游走，生成新序列
    newSamples = randomWalk(transitionMatrix, itemDistribution, sampleCount, sampleLength)
    
    # Step 4: 将新序列转换为 RDD 格式
    rddSamples = spark.sparkContext.parallelize(newSamples)
    
    # Step 5: 使用随机游走序列训练 Word2Vec
    trainItem2vec(spark, rddSamples, embLength, embOutputFilename, saveToRedis, redisKeyPrefix)


def generateUserEmb(spark, rawSampleDataPath, model, embLength, embOutputPath, saveToRedis, redisKeyPrefix):
    """
    生成用户 Embedding 向量
    
    用户 Embedding 生成原理:
    ================================
    核心思想: 用户的兴趣可以用其观看/购买过的物品来表示
    
    常见方法:
    1. 平均池化 (Mean Pooling): 用户 Embedding = 所有物品 Embedding 的平均值
    2. 求和 (Sum): 用户 Embedding = 所有物品 Embedding 的和 (本函数使用的方法)
    3. 加权平均: 根据用户对物品的评分或交互时间进行加权
    4. 注意力机制: 使用神经网络学习不同物品的重要性权重
    
    本函数使用求和方法:
    UserEmb = Σ ItemEmb (对用户观看过的所有电影)
    
    优点:
    - 简单高效，易于实现
    - 不需要额外的模型训练
    - 可以实时更新 (用户新行为只需加上新物品的 Embedding)
    
    缺点:
    - 没有考虑物品的重要性差异
    - 向量会随着用户行为数量增加而增大
    - 无法区分用户对不同物品的喜好程度
    
    参数:
        spark: SparkSession 实例
        rawSampleDataPath: 原始评分数据路径
        model: 训练好的 Word2Vec 模型 (包含物品 Embedding)
        embLength: Embedding 向量维度
        embOutputPath: 输出文件路径
        saveToRedis: 是否保存到 Redis
        redisKeyPrefix: Redis 键前缀
    
    数据流程:
        评分数据 + 物品Embedding -> Join -> 按用户聚合求和 -> 用户Embedding
    """
    # 读取评分数据
    ratingSamples = spark.read.format("csv").option("header", "true").load(rawSampleDataPath)
    
    # 将模型中的物品 Embedding 转换为列表格式
    Vectors_list = []
    for key, value in model.getVectors().items():
        Vectors_list.append((key, list(value)))
    
    # 定义 DataFrame Schema
    fields = [
        StructField('movieId', StringType(), False),      # 电影ID
        StructField('emb', ArrayType(FloatType()), False) # Embedding 向量
    ]
    schema = StructType(fields)
    
    # 创建物品 Embedding 的 DataFrame
    Vectors_df = spark.createDataFrame(Vectors_list, schema=schema)
    
    # 将评分数据与物品 Embedding 进行 Join
    # Inner Join 确保只保留有 Embedding 的电影
    ratingSamples = ratingSamples.join(Vectors_df, on='movieId', how='inner')
    
    # 按用户聚合，对物品 Embedding 求和
    # 1. 选择 userId 和 emb 列
    # 2. 转换为 (userId, emb) 的 RDD
    # 3. reduceByKey: 将同一用户的所有物品 Embedding 逐元素相加
    result = ratingSamples.select('userId', 'emb').rdd \
        .map(lambda x: (x[0], x[1])) \
        .reduceByKey(lambda a, b: [a[i] + b[i] for i in range(len(a))]) \
        .collect()
    
    # 保存用户 Embedding 到文件
    with open(embOutputPath, 'w') as f:
        for row in result:
            vectors = " ".join([str(emb) for emb in row[1]])
            f.write(row[0] + ":" + vectors + "\n")


# =====================================================================================
# 主程序入口
# =====================================================================================
if __name__ == '__main__':
    """
    程序执行流程:
    ================================
    1. 初始化 Spark 环境
    2. 处理原始数据，生成用户观影序列
    3. 训练 Item2Vec 模型，学习电影 Embedding
    4. 训练 Graph Embedding (DeepWalk)
    5. 生成用户 Embedding
    
    输出文件:
    - item2vecEmb.csv: Item2Vec 学习的电影 Embedding
    - itemGraphEmb.csv: Graph Embedding 学习的电影 Embedding
    - userEmb.csv: 基于电影 Embedding 聚合的用户 Embedding
    """
    
    # ========== Step 1: 初始化 Spark 环境 ==========
    # SparkConf 用于配置 Spark 应用
    # - setAppName: 应用名称，用于在 Spark UI 中标识
    # - setMaster: 运行模式，'local' 表示本地单机模式
    conf = SparkConf().setAppName('ctrModel').setMaster('local')
    
    # 创建 SparkSession，这是 Spark 2.0+ 的统一入口点
    spark = SparkSession.builder.config(conf=conf).getOrCreate()
    
    # ========== Step 2: 配置文件路径 ==========
    # 注意: 请根据实际环境修改路径
    file_path = 'file:///Users/spike/Projects/SparrowRecSys/src/main/resources'
    rawSampleDataPath = file_path + "/webroot/sampledata/ratings.csv"
    
    # Embedding 向量维度
    # 通常在 10-300 之间，维度越高表达能力越强但计算量越大
    embLength = 10
    
    # ========== Step 3: 数据预处理 ==========
    # 生成用户的观影序列，用于后续的 Embedding 训练
    samples = processItemSequence(spark, rawSampleDataPath)
    
    # ========== Step 4: 训练 Item2Vec ==========
    # 使用原始观影序列训练 Word2Vec 模型
    model = trainItem2vec(
        spark, 
        samples, 
        embLength,
        embOutputPath=file_path[7:] + "/webroot/modeldata2/item2vecEmb.csv",
        saveToRedis=False,
        redisKeyPrefix="i2vEmb"
    )
    
    # ========== Step 5: 训练 Graph Embedding ==========
    # 使用 DeepWalk 算法: 随机游走 + Word2Vec
    graphEmb(
        samples, 
        spark, 
        embLength, 
        embOutputFilename=file_path[7:] + "/webroot/modeldata2/itemGraphEmb.csv",
        saveToRedis=True, 
        redisKeyPrefix="graphEmb"
    )
    
    # ========== Step 6: 生成用户 Embedding ==========
    # 通过聚合用户观看过的电影的 Embedding 来生成用户 Embedding
    generateUserEmb(
        spark, 
        rawSampleDataPath, 
        model, 
        embLength,
        embOutputPath=file_path[7:] + "/webroot/modeldata2/userEmb.csv",
        saveToRedis=False,
        redisKeyPrefix="uEmb"
    )
