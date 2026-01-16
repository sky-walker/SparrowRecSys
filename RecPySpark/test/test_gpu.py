import tensorflow as tf

# 检查 TensorFlow 版本
print(f"TensorFlow version: {tf.__version__}")

# 检查是否检测到 GPU
print("GPU devices:", tf.config.list_physical_devices('GPU'))

# 应该输出类似：
# GPU devices: [PhysicalDevice(name='/physical_device:GPU:0', device_type='GPU')]