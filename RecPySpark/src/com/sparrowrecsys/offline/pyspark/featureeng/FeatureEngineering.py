"""
==============================================================================
特征工程 (Feature Engineering) - 推荐系统中最重要的环节之一
==============================================================================

什么是特征工程？
----------------
特征工程是将原始数据转换为机器学习模型能够理解和使用的数值特征的过程。
在推荐系统中，好的特征工程能够显著提升模型效果。

本文件演示了推荐系统中常用的三种特征处理技术：
1. One-Hot 编码 (独热编码) - 处理单值类别特征
2. Multi-Hot 编码 (多热编码) - 处理多值类别特征  
3. 数值特征处理 - 包括分桶(Bucketing)和归一化(Normalization)

为什么需要特征工程？
-------------------
- 原始数据（如电影ID、类型名称）是文本或类别，机器学习模型无法直接处理
- 需要将其转换为数值向量形式
- 不同特征的数值范围差异大，需要归一化处理
"""

import os
import sys

# ==============================================================================
# 环境配置
# ==============================================================================
# 设置 PySpark 使用当前 Python 解释器
# 这是为了避免 Driver（驱动程序）和 Executor（执行器）使用不同版本的 Python
# 如果版本不匹配，会导致序列化/反序列化错误
os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable

# ==============================================================================
# 导入依赖库
# ==============================================================================
from pyspark import SparkConf                    # Spark 配置类
from pyspark.ml import Pipeline                   # 机器学习管道，用于串联多个处理步骤
from pyspark.ml.feature import (
    OneHotEncoder,           # One-Hot 编码器
    StringIndexer,           # 字符串索引器，将字符串转换为数字索引
    QuantileDiscretizer,     # 分位数离散化器，用于分桶
    MinMaxScaler             # 最大最小值归一化器
)
from pyspark.ml.linalg import VectorUDT, Vectors  # 向量类型，用于机器学习
from pyspark.sql import SparkSession              # Spark SQL 会话入口
from pyspark.sql.functions import *               # SQL 函数（如 col, explode, split 等）
from pyspark.sql.types import *                   # 数据类型（如 IntegerType, StringType 等）
from pyspark.sql import functions as F            # 为 SQL 函数设置别名，避免命名冲突


# ==============================================================================
# One-Hot 编码示例
# ==============================================================================
def oneHotEncoderExample(movieSamples):
    """
    One-Hot 编码（独热编码）演示
    
    什么是 One-Hot 编码？
    --------------------
    One-Hot 编码将类别值转换为二进制向量，其中只有一个位置为1，其余为0。
    
    举例：假设有3部电影，ID分别是 1, 2, 3
    - 电影1 -> [1, 0, 0]
    - 电影2 -> [0, 1, 0]  
    - 电影3 -> [0, 0, 1]
    
    为什么使用 One-Hot 编码？
    -----------------------
    1. 消除数值大小的影响：如果直接使用 movieId=1, 2, 3，
       模型可能会认为电影3"大于"电影1，这是没有意义的
    2. 机器学习模型（尤其是线性模型）更容易处理这种表示
    
    注意事项：
    ---------
    - 当类别数量很大时（如百万级电影），One-Hot 向量会非常稀疏
    - 这种情况下通常使用 Embedding（嵌入）来替代
    
    参数:
        movieSamples: 包含电影信息的 DataFrame
    """
    # Step 1: 将 movieId 从字符串转换为整数类型
    # 因为 OneHotEncoder 需要数值类型的输入
    # withColumn 用于添加新列或替换现有列
    samplesWithIdNumber = movieSamples.withColumn(
        "movieIdNumber",                    # 新列名
        F.col("movieId").cast(IntegerType())  # 将 movieId 列转换为整数类型
    )
    
    # Step 2: 创建 OneHotEncoder 实例
    # inputCols: 输入列名（需要编码的列）
    # outputCols: 输出列名（编码后的向量列）
    # dropLast=False: 不删除最后一个类别（默认会删除以避免多重共线性）
    encoder = OneHotEncoder(
        inputCols=["movieIdNumber"], 
        outputCols=['movieIdVector'], 
        dropLast=False
    )
    
    # Step 3: fit() 学习数据，transform() 应用转换
    # fit(): 学习所有唯一的 movieId 值，确定向量维度
    # transform(): 将每个 movieId 转换为对应的 One-Hot 向量
    oneHotEncoderSamples = encoder.fit(samplesWithIdNumber).transform(samplesWithIdNumber)
    
    # 打印结果的 Schema（数据结构）和示例数据
    oneHotEncoderSamples.printSchema()  # 显示列名和数据类型
    oneHotEncoderSamples.show(10)       # 显示前10行数据


# ==============================================================================
# 辅助函数：将索引数组转换为稀疏向量
# ==============================================================================
def array2vec(genreIndexes, indexSize):
    """
    将类型索引数组转换为稀疏向量 (Sparse Vector)
    
    什么是稀疏向量？
    ---------------
    当向量中大部分元素为0时，存储所有元素很浪费空间。
    稀疏向量只存储非零元素的位置和值。
    
    举例：一个19维向量，只有第2和第5位为1
    - 密集表示: [0,0,1,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0]
    - 稀疏表示: (19, [2,5], [1.0,1.0])
      - 19: 向量总维度
      - [2,5]: 非零元素的索引位置
      - [1.0,1.0]: 非零元素的值
    
    参数:
        genreIndexes: 类型索引列表，如 [2, 5] 表示该电影属于第2和第5种类型
        indexSize: 向量的总维度（类型总数）
        
    返回:
        稀疏向量表示
    """
    # 对索引排序，这是 Spark 稀疏向量的要求
    genreIndexes.sort()
    # 创建值列表，每个非零位置的值都是 1.0（表示"属于该类型"）
    fill_list = [1.0 for _ in range(len(genreIndexes))]
    # 创建并返回稀疏向量
    return Vectors.sparse(indexSize, genreIndexes, fill_list)


# ==============================================================================
# Multi-Hot 编码示例
# ==============================================================================
def multiHotEncoderExample(movieSamples):
    """
    Multi-Hot 编码（多热编码）演示
    
    什么是 Multi-Hot 编码？
    ----------------------
    当一个样本可以同时属于多个类别时，使用 Multi-Hot 编码。
    与 One-Hot 不同，Multi-Hot 向量中可以有多个位置为1。
    
    场景：一部电影可以有多个类型（如同时是 Action 和 Comedy）
    
    举例：假设有5种电影类型：Action, Comedy, Drama, Horror, Sci-Fi
    - 《复仇者联盟》(Action|Sci-Fi) -> [1, 0, 0, 0, 1]
    - 《喜剧之王》(Comedy|Drama)    -> [0, 1, 1, 0, 0]
    
    处理流程：
    ---------
    1. 将 "Action|Comedy|Drama" 拆分成多行
    2. 将每个类型名称转换为数字索引
    3. 按电影分组，收集所有类型索引
    4. 转换为稀疏向量
    
    参数:
        movieSamples: 包含电影信息的 DataFrame，genres 列格式如 "Action|Comedy"
    """
    # Step 1: 展开类型字段
    # 原始数据: movieId=1, genres="Action|Comedy"
    # 处理后:   movieId=1, genre="Action"
    #          movieId=1, genre="Comedy"
    # 
    # split(): 按 "|" 分割字符串，得到数组 ["Action", "Comedy"]
    # explode(): 将数组展开成多行
    samplesWithGenre = movieSamples.select(
        "movieId", 
        "title", 
        explode(
            split(F.col("genres"), "\\|")  # "\\|" 是正则表达式中的 "|"
            .cast(ArrayType(StringType()))  # 转换为字符串数组类型
        ).alias('genre')  # 展开后的列名为 'genre'
    )
    
    # Step 2: 将类型名称转换为数字索引
    # 例如: Action->0, Comedy->1, Drama->2, ...
    # StringIndexer 会按照出现频率排序（最常见的类型索引最小）
    genreIndexer = StringIndexer(inputCol="genre", outputCol="genreIndex")
    StringIndexerModel = genreIndexer.fit(samplesWithGenre)  # 学习所有类型
    
    # 应用转换，并将索引转换为整数类型（原本是 Double）
    genreIndexSamples = StringIndexerModel.transform(samplesWithGenre).withColumn(
        "genreIndexInt",
        F.col("genreIndex").cast(IntegerType())
    )
    
    # Step 3: 计算类型总数（用于确定向量维度）
    # 最大索引值 + 1 = 类型总数
    # agg(max(...)): 聚合操作，找最大值
    # head()[0]: 获取结果的第一行第一列
    indexSize = genreIndexSamples.agg(max(F.col("genreIndexInt"))).head()[0] + 1
    
    # Step 4: 按电影分组，收集每部电影的所有类型索引
    # 例如: movieId=1 -> genreIndexes=[0, 3, 5]
    # groupBy(): 按 movieId 分组
    # collect_list(): 将组内的所有值收集到一个列表中
    processedSamples = genreIndexSamples.groupBy('movieId').agg(
        F.collect_list('genreIndexInt').alias('genreIndexes')
    ).withColumn("indexSize", F.lit(indexSize))  # lit() 创建常量列
    
    # Step 5: 使用自定义函数 (UDF) 将索引列表转换为稀疏向量
    # udf(): User Defined Function，用户自定义函数
    # VectorUDT(): 返回值类型是向量
    finalSample = processedSamples.withColumn(
        "vector",
        udf(array2vec, VectorUDT())(F.col("genreIndexes"), F.col("indexSize"))
    )
    
    # 打印结果
    finalSample.printSchema()
    finalSample.show(10)


# ==============================================================================
# 数值特征处理示例
# ==============================================================================
def ratingFeatures(ratingSamples):
    """
    数值特征处理演示 - 分桶 (Bucketing) 和 归一化 (Normalization)
    
    为什么需要处理数值特征？
    ----------------------
    1. 数值范围差异大：评分次数可能是1-100000，评分可能是1-5
       不同量级的特征会影响模型训练
    2. 连续值离散化：将连续值分桶可以增强模型的非线性表达能力
    3. 归一化：将特征缩放到统一范围，加速模型收敛
    
    本函数演示两种技术：
    1. 分桶 (Bucketing): 将评分次数离散化到100个桶中
    2. 归一化 (Normalization): 将平均评分缩放到 [0, 1] 范围
    
    参数:
        ratingSamples: 包含用户评分的 DataFrame (userId, movieId, rating, timestamp)
    """
    # 查看原始数据结构和内容
    ratingSamples.printSchema()
    ratingSamples.show()
    
    # ===========================================================================
    # Step 1: 特征聚合 - 计算每部电影的统计特征
    # ===========================================================================
    # groupBy('movieId'): 按电影分组
    # agg(): 聚合计算多个统计量
    #   - count(): 评分次数（电影热门程度的指标）
    #   - avg(): 平均评分（电影质量的指标）
    #   - variance(): 评分方差（评分是否有争议的指标）
    movieFeatures = ratingSamples.groupBy('movieId').agg(
        F.count(F.lit(1)).alias('ratingCount'),      # 评分总次数
        F.avg("rating").alias("avgRating"),           # 平均评分
        F.variance('rating').alias('ratingVar')       # 评分方差
    ).withColumn(
        # 将平均评分转换为向量格式（MinMaxScaler 需要向量输入）
        # Vectors.dense(x): 创建密集向量
        'avgRatingVec', 
        udf(lambda x: Vectors.dense(x), VectorUDT())('avgRating')
    )
    
    movieFeatures.show(10)
    
    # ===========================================================================
    # Step 2: 分桶 (Bucketing / Discretization)
    # ===========================================================================
    # 什么是分桶？
    # 将连续数值划分到离散的区间（桶）中
    # 
    # 为什么要分桶？
    # 1. 减少噪声影响：评分次数 998 和 1002 本质差异不大
    # 2. 特征交叉：离散特征更容易做特征交叉
    # 3. 非线性表达：分桶后可以为每个桶学习不同的权重
    #
    # QuantileDiscretizer 使用分位数方法分桶
    # 例如分100桶，每个桶包含约1%的数据，这样可以处理长尾分布
    ratingCountDiscretizer = QuantileDiscretizer(
        numBuckets=100,            # 分成100个桶
        inputCol="ratingCount",    # 输入列
        outputCol="ratingCountBucket"  # 输出列（桶的编号 0-99）
    )
    
    # ===========================================================================
    # Step 3: 归一化 (Normalization)
    # ===========================================================================
    # 什么是归一化？
    # 将数值缩放到统一的范围，通常是 [0, 1] 或 [-1, 1]
    #
    # MinMaxScaler 公式: x_scaled = (x - min) / (max - min)
    # 
    # 为什么要归一化？
    # 1. 消除量纲影响：让不同特征在同一尺度上
    # 2. 加速训练：梯度下降更容易收敛
    # 3. 提升效果：某些模型（如神经网络）对特征尺度敏感
    ratingScaler = MinMaxScaler(
        inputCol="avgRatingVec",       # 输入向量列
        outputCol="scaleAvgRating"     # 输出归一化后的向量
    )
    
    # ===========================================================================
    # Step 4: 使用 Pipeline 串联多个处理步骤
    # ===========================================================================
    # Pipeline（管道）的优势：
    # 1. 代码清晰：将多个处理步骤组织在一起
    # 2. 方便复用：可以保存管道模型，应用到新数据
    # 3. 防止数据泄露：fit 和 transform 分离，避免用测试数据训练
    pipelineStage = [ratingCountDiscretizer, ratingScaler]  # 处理步骤列表
    featurePipeline = Pipeline(stages=pipelineStage)        # 创建管道
    
    # fit(): 在数据上学习（计算分位数、最大最小值等）
    # transform(): 应用转换
    movieProcessedFeatures = featurePipeline.fit(movieFeatures).transform(movieFeatures)
    
    # 打印处理后的结果
    # 新增列: ratingCountBucket (分桶结果), scaleAvgRating (归一化评分)
    movieProcessedFeatures.show(10)


# ==============================================================================
# 主程序入口
# ==============================================================================
if __name__ == '__main__':
    """
    主程序执行流程：
    1. 创建 Spark 会话
    2. 加载电影数据
    3. 演示 One-Hot 编码
    4. 演示 Multi-Hot 编码
    5. 加载评分数据
    6. 演示数值特征处理
    """
    
    # ===========================================================================
    # Step 1: 创建 Spark 会话
    # ===========================================================================
    # SparkConf: Spark 配置对象
    # setAppName: 设置应用名称（在 Spark UI 中显示）
    # setMaster('local'): 本地模式运行，用于开发测试
    #   - 'local': 单线程
    #   - 'local[4]': 4个线程
    #   - 'local[*]': 使用所有可用 CPU 核心
    #   - 生产环境使用 'yarn' 或 'spark://host:port'
    conf = SparkConf().setAppName('featureEngineering').setMaster('local')
    
    # SparkSession: Spark 2.0+ 的统一入口点
    # 整合了 SparkContext, SQLContext, HiveContext 的功能
    spark = SparkSession.builder.config(conf=conf).getOrCreate()
    
    # ===========================================================================
    # Step 2: 加载电影数据
    # ===========================================================================
    # file:// 前缀表示本地文件系统
    # 生产环境通常使用 hdfs:// 或 s3:// 等分布式存储
    file_path = 'file:///Users/spike/Projects/SparrowRecSys/src/main/resources'
    movieResourcesPath = file_path + "/webroot/sampledata/movies.csv"
    
    # 使用 Spark 读取 CSV 文件
    # format('csv'): 指定文件格式
    # option('header', 'true'): 第一行是表头
    # load(): 加载数据，返回 DataFrame
    movieSamples = spark.read.format('csv').option('header', 'true').load(movieResourcesPath)
    
    # 查看原始数据
    print("Raw Movie Samples:")
    movieSamples.show(10)      # 显示前10行
    movieSamples.printSchema()  # 显示数据结构
    
    # ===========================================================================
    # Step 3: 运行特征工程示例
    # ===========================================================================
    
    # 示例1: One-Hot 编码
    # 将单值类别（movieId）转换为独热向量
    print("OneHotEncoder Example:")
    oneHotEncoderExample(movieSamples)
    
    # 示例2: Multi-Hot 编码
    # 将多值类别（genres，如 "Action|Comedy"）转换为多热向量
    print("MultiHotEncoder Example:")
    multiHotEncoderExample(movieSamples)
    
    # 示例3: 数值特征处理
    # 演示分桶和归一化
    print("Numerical features Example:")
    ratingsResourcesPath = file_path + "/webroot/sampledata/ratings.csv"
    ratingSamples = spark.read.format('csv').option('header', 'true').load(ratingsResourcesPath)
    ratingFeatures(ratingSamples)
