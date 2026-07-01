import tensorflow as tf
from tensorflow.keras import layers, models, Input
import numpy as np
import os

# ==============================================================================
# [1] 모델 정의
# ==============================================================================

def build_resnet10_1d(input_shape=(40, 40), num_classes=50):
    """
    [Distributed Target] 고성능, 고연산량 모델
    - ESP32 하나에 올리기엔 RAM/Flash가 부담스럽거나 연산이 오래 걸림
    - 분산 처리를 통해 Latency와 Memory 부담을 나눔
    """
    inputs = Input(shape=input_shape)
    # Stem
    x = layers.Conv1D(64, 7, strides=2, padding="same")(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    x = layers.MaxPooling1D(3, strides=2, padding="same")(x)
    
    # ResBlocks (Simplified for demo)
    # 4 blocks, increasing filters
    for filters in [64, 128, 256, 512]:
        shortcut = layers.Conv1D(filters, 1, strides=2, padding="same")(x)
        x = layers.Conv1D(filters, 3, strides=2, padding="same")(x)
        x = layers.BatchNormalization()(x)
        x = layers.ReLU()(x)
        x = layers.Conv1D(filters, 3, strides=1, padding="same")(x)
        x = layers.BatchNormalization()(x)
        x = layers.Add()([x, shortcut])
        x = layers.ReLU()(x)
        
    x = layers.GlobalAveragePooling1D()(x)
    outputs = layers.Dense(num_classes, activation="softmax")(x)
    return models.Model(inputs, outputs, name="ResNet10_Distributed")

def build_dscnn_tiny(input_shape=(40, 40), num_classes=50):
    """
    [Single Node Target] 초경량 모델 (DS-CNN)
    - Depthwise Separable Convolution 사용으로 연산량 극소화
    - 정확도는 떨어지지만 ESP32 한 대에서 완결 가능
    """
    inputs = Input(shape=input_shape)
    
    # Standard Conv (Stem)
    x = layers.Conv1D(32, 3, strides=2, padding="same")(inputs)
    x = layers.BatchNormalization()(x)
    x = layers.ReLU()(x)
    
    # DS-CNN Blocks (Lightweight)
    for filters in [32, 64, 64]:
        # Depthwise
        x = layers.DepthwiseConv1D(3, strides=2, padding="same")(x)
        x = layers.BatchNormalization()(x)
        x = layers.ReLU()(x)
        # Pointwise
        x = layers.Conv1D(filters, 1, strides=1, padding="same")(x)
        x = layers.BatchNormalization()(x)
        x = layers.ReLU()(x)

    x = layers.GlobalAveragePooling1D()(x)
    outputs = layers.Dense(num_classes, activation="softmax")(x)
    return models.Model(inputs, outputs, name="DSCNN_Tiny")

# ==============================================================================
# [2] 모델 변환 및 프로파일링
# ==============================================================================
def get_model_size_and_flops(model, name):
    # 1. TFLite 변환 (Int8 Quantization)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    
    # Dummy representative dataset
    def representative_data_gen():
        for _ in range(10):
            yield [np.random.rand(1, 40, 40).astype(np.float32)]
            
    converter.representative_dataset = representative_data_gen
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    
    tflite_model = converter.convert()
    
    # 저장
    filename = f"{name}.tflite"
    with open(filename, "wb") as f:
        f.write(tflite_model)
    
    size_kb = len(tflite_model) / 1024
    
    # FLOPs 추정 (Simple calculation via Keras param count rough estimation)
    # 실제로는 TensorFlow Profiler를 써야 정확하지만, 여기서는 파라미터 수 비례로 가정
    total_params = model.count_params()
    est_flops = total_params * 2.0 # Rough estimation
    
    return size_kb, est_flops, filename

# 실행
if __name__ == "__main__":
    # 데이터셋 형상
    input_shape = (40, 40)
    
    # 1. Distributed Model (ResNet10)
    model_dist = build_resnet10_1d(input_shape)
    size_dist, flops_dist, _ = get_model_size_and_flops(model_dist, "resnet10_dist")
    
    # 2. Single Tiny Model (DS-CNN)
    model_tiny = build_dscnn_tiny(input_shape)
    size_tiny, flops_tiny, _ = get_model_size_and_flops(model_tiny, "dscnn_tiny")
    
    print("="*60)
    print(f"Model Profiling Results (to be used in Simulation)")
    print("="*60)
    print(f"[1] ResNet-10 (Distributed Target)")
    print(f"    - Size: {size_dist:.2f} KB")
    print(f"    - Est. Params: {model_dist.count_params():,}")
    print(f"    - Relative Compute Load: 100% (Baseline for heavy)")
    print("-" * 60)
    print(f"[2] DS-CNN (Single Tiny Target)")
    print(f"    - Size: {size_tiny:.2f} KB")
    print(f"    - Est. Params: {model_tiny.count_params():,}")
    print(f"    - Size Ratio: {size_tiny/size_dist*100:.1f}% of ResNet")
    print("="*60)