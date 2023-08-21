import matplotlib.pyplot as plt

# 定义自动编码器图的元素
input_data = 'Input Data'
encoded_data = 'Encoded Data'
decoded_data = 'Decoded Data'
code = 'Code'

# 创建图形
fig, ax = plt.subplots()

# 设置图形的标题和坐标轴
ax.set_title('Autoencoder')
ax.axis('off')

# 绘制自动编码器的图形元素
ax.text(0.5, 0.9, input_data, ha='center', va='center', fontsize=12, bbox=dict(facecolor='lightgray', edgecolor='gray', boxstyle='round,pad=0.3'))
ax.text(0.2, 0.6, encoded_data, ha='center', va='center', fontsize=12, bbox=dict(facecolor='lightgray', edgecolor='gray', boxstyle='round,pad=0.3'))
ax.text(0.8, 0.6, decoded_data, ha='center', va='center', fontsize=12, bbox=dict(facecolor='lightgray', edgecolor='gray', boxstyle='round,pad=0.3'))
ax.text(0.5, 0.4, code, ha='center', va='center', fontsize=12, bbox=dict(facecolor='lightgray', edgecolor='gray', boxstyle='round,pad=0.3'))

# 绘制箭头连接各个元素
arrow_args = dict(arrowstyle='->', color='black')
ax.annotate('', xy=(0.5, 0.85), xytext=(0.2, 0.65), arrowprops=arrow_args)
ax.annotate('', xy=(0.5, 0.85), xytext=(0.8, 0.65), arrowprops=arrow_args)
ax.annotate('', xy=(0.2, 0.55), xytext=(0.5, 0.45), arrowprops=arrow_args)
ax.annotate('', xy=(0.8, 0.55), xytext=(0.5, 0.45), arrowprops=arrow_args)

# 显示图形
plt.show()
