import tensorflow as tf

# Training samples path, change to your local path
training_samples_file_path = tf.keras.utils.get_file("trainingSamples.csv",
                                                     "file:///Users/spike/Projects/SparrowRecSys/src/main"
                                                     "/resources/webroot/sampledata/trainingSamples.csv")
# Test samples path, change to your local path
test_samples_file_path = tf.keras.utils.get_file("testSamples.csv",
                                                 "file:///Users/spike/Projects/SparrowRecSys/src/main"
                                                 "/resources/webroot/sampledata/testSamples.csv")


# 优化1: 数据管道优化 - 添加 shuffle, cache, prefetch
def get_dataset(file_path, is_training=False):
    dataset = tf.data.experimental.make_csv_dataset(
        file_path,
        batch_size=64,
        label_name='label',
        na_value="0",
        num_epochs=1,
        ignore_errors=True)
    
    if is_training:
        dataset = dataset.shuffle(buffer_size=10000)  # 打乱数据，提高泛化能力
    
    dataset = dataset.cache()                         # 缓存到内存，避免重复读取
    dataset = dataset.prefetch(tf.data.AUTOTUNE)      # 异步预取，提高吞吐量
    return dataset


# split as test dataset and training dataset
train_dataset = get_dataset(training_samples_file_path, is_training=True)
test_dataset = get_dataset(test_samples_file_path, is_training=False)

# genre features vocabulary
genre_vocab = ['Film-Noir', 'Action', 'Adventure', 'Horror', 'Romance', 'War', 'Comedy', 'Western', 'Documentary',
               'Sci-Fi', 'Drama', 'Thriller',
               'Crime', 'Fantasy', 'Animation', 'IMAX', 'Mystery', 'Children', 'Musical']

# 优化4: 调整 Embedding 维度
GENRE_FEATURES = {
    'userGenre1': genre_vocab,
    'userGenre2': genre_vocab,
    'userGenre3': genre_vocab,
    'userGenre4': genre_vocab,
    'userGenre5': genre_vocab,
    'movieGenre1': genre_vocab,
    'movieGenre2': genre_vocab,
    'movieGenre3': genre_vocab
}

# all categorical features with optimized embedding dimensions
categorical_columns = []
for feature, vocab in GENRE_FEATURES.items():
    cat_col = tf.feature_column.categorical_column_with_vocabulary_list(
        key=feature, vocabulary_list=vocab)
    emb_col = tf.feature_column.embedding_column(cat_col, 8)  # genre: 19类 -> 8维
    categorical_columns.append(emb_col)

# movie id embedding feature - 优化维度
movie_col = tf.feature_column.categorical_column_with_identity(key='movieId', num_buckets=1001)
movie_emb_col = tf.feature_column.embedding_column(movie_col, 16)  # 1001类 -> 16维
categorical_columns.append(movie_emb_col)

# user id embedding feature - 优化维度
user_col = tf.feature_column.categorical_column_with_identity(key='userId', num_buckets=30001)
user_emb_col = tf.feature_column.embedding_column(user_col, 32)  # 30001类 -> 32维
categorical_columns.append(user_emb_col)

# 优化3: 数值特征归一化
# 对计数类特征使用 log 变换，对年份进行标准化
numerical_columns = [
    tf.feature_column.numeric_column('releaseYear',
        normalizer_fn=lambda x: (tf.cast(x, tf.float32) - 1990.0) / 30.0),  # 标准化年份
    tf.feature_column.numeric_column('movieRatingCount',
        normalizer_fn=lambda x: tf.math.log1p(tf.cast(x, tf.float32))),     # log(1+x) 变换
    tf.feature_column.numeric_column('movieAvgRating',
        normalizer_fn=lambda x: (tf.cast(x, tf.float32) - 2.5) / 2.5),      # 标准化到 [-1, 1]
    tf.feature_column.numeric_column('movieRatingStddev'),                   # 标准差本身尺度合理
    tf.feature_column.numeric_column('userRatingCount',
        normalizer_fn=lambda x: tf.math.log1p(tf.cast(x, tf.float32))),     # log(1+x) 变换
    tf.feature_column.numeric_column('userAvgRating',
        normalizer_fn=lambda x: (tf.cast(x, tf.float32) - 2.5) / 2.5),      # 标准化到 [-1, 1]
    tf.feature_column.numeric_column('userRatingStddev')                     # 标准差本身尺度合理
]

# 优化5: 模型架构优化 - 金字塔结构 + L2 正则 + BatchNorm
model = tf.keras.Sequential([
    tf.keras.layers.DenseFeatures(numerical_columns + categorical_columns),
    tf.keras.layers.BatchNormalization(),
    
    # 第一层: 256 units
    tf.keras.layers.Dense(256, activation='relu',
        kernel_regularizer=tf.keras.regularizers.l2(1e-5)),
    tf.keras.layers.BatchNormalization(),
    tf.keras.layers.Dropout(0.3),
    
    # 第二层: 128 units (递减)
    tf.keras.layers.Dense(128, activation='relu',
        kernel_regularizer=tf.keras.regularizers.l2(1e-5)),
    tf.keras.layers.BatchNormalization(),
    tf.keras.layers.Dropout(0.2),
    
    # 第三层: 64 units (继续递减)
    tf.keras.layers.Dense(64, activation='relu',
        kernel_regularizer=tf.keras.regularizers.l2(1e-5)),
    
    # 输出层
    tf.keras.layers.Dense(1, activation='sigmoid'),
])

# 优化7: 添加标签平滑，防止过拟合
# compile the model, set loss function, optimizer and evaluation metrics
model.compile(
    loss=tf.keras.losses.BinaryCrossentropy(label_smoothing=0.1),  # 标签平滑
    optimizer=tf.keras.optimizers.legacy.Adam(learning_rate=0.001, clipnorm=1.0),
    metrics=['accuracy', tf.keras.metrics.AUC(curve='ROC'), tf.keras.metrics.AUC(curve='PR')])

# 优化6: 早停基于验证集 loss
early_stop = tf.keras.callbacks.EarlyStopping(
    monitor='val_loss',  # 改为监控验证集 loss
    patience=3, 
    restore_best_weights=True, 
    verbose=1
)
lr_scheduler = tf.keras.callbacks.ReduceLROnPlateau(
    monitor='val_loss',  # 改为监控验证集 loss
    factor=0.5, 
    patience=2, 
    min_lr=1e-6, 
    verbose=1
)

# train the model with validation split
# 优化6: 使用验证集进行早停判断
model.fit(
    train_dataset, 
    epochs=20,  # 增加 epochs，让早停决定何时停止
    validation_data=test_dataset,  # 使用测试集作为验证集
    callbacks=[early_stop, lr_scheduler]
)

# evaluate the model
test_loss, test_accuracy, test_roc_auc, test_pr_auc = model.evaluate(test_dataset)
print('\n\nTest Loss {}, Test Accuracy {}, Test ROC AUC {}, Test PR AUC {}'.format(test_loss, test_accuracy,
                                                                                   test_roc_auc, test_pr_auc))

# print some predict results
predictions = model.predict(test_dataset)
for prediction, goodRating in zip(predictions[:12], list(test_dataset)[0][1][:12]):
    print("Predicted good rating: {:.2%}".format(prediction[0]),
          " | Actual rating label: ",
          ("Good Rating" if bool(goodRating) else "Bad Rating"))
