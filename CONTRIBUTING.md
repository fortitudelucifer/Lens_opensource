# Contributing to Lens_opensource

感谢您对 Lens_opensource 项目的关注！我们欢迎各种形式的贡献。

## 🤝 贡献方式

### 报告问题
- 使用 [GitHub Issues](../../issues) 报告bug
- 提供详细的错误信息和复现步骤
- 包含系统环境信息

### 功能建议
- 在 Issues 中描述新功能需求
- 说明使用场景和预期效果
- 讨论实现方案

### 代码贡献
1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 📋 开发指南

### 环境设置
```bash
# 克隆仓库
git clone https://github.com/fortitudelucifer/Lens_opensource.git
cd Lens_opensource

# 创建虚拟环境
conda env create -f environment.yml
conda activate chat_app_dha

# 或使用pip
pip install -r requirements.txt
```

### 代码规范
- 使用 Python 3.10+
- 遵循 PEP 8 代码风格
- 添加适当的注释和文档字符串
- 使用类型提示 (Type Hints)

### 测试
```bash
# 运行测试
python -m pytest tests/

# 代码格式检查
black scripts/
flake8 scripts/
```

## 🏗️ 项目结构

```
Lens_opensource/
├── scripts/                 # 核心脚本
│   ├── workspace/         # 数据归一化
│   ├── image/             # 图片处理
│   ├── voice/             # 语音处理
│   ├── video/             # 视频处理
│   ├── sticker/           # 表情包处理
│   ├── linkfile/          # 链接文件处理
│   ├── advisor/           # 关系顾问
│   ├── compression/       # 数据压缩
│   └── _common/           # 共享工具
├── configs/               # 配置文件
├── docs/                  # 文档
├── frontend/              # 前端代码
└── tests/                 # 测试文件
```

## 📝 贡献类型

### 🐛 Bug修复
- 修复现有功能的问题
- 确保向后兼容性
- 添加相关测试

### ✨ 新功能
- 实现新的处理模态
- 优化现有算法
- 添加新的分析功能

### 📚 文档改进
- 完善API文档
- 添加使用示例
- 翻译文档

### 🔧 工具和脚本
- 开发新的适配器
- 创建辅助工具
- 优化性能

## 🎯 贡献重点领域

### 1. 数据适配器
- 支持更多聊天平台 (Discord, Slack, Line等)
- 改进现有适配器的兼容性
- 添加数据验证功能

### 2. 模态处理
- 新的模态支持 (文档PDF、音频文件等)
- 提高OCR准确率
- 优化视频关键帧提取

### 3. AI模型集成
- 支持更多开源模型
- 模型性能优化
- 本地模型部署方案

### 4. 隐私保护
- 改进PII检测算法
- 添加新的匿名化策略
- 隐私保护评估工具

### 5. 用户体验
- 前端界面改进
- 配置向导
- 错误提示优化

## 📤 提交规范

### Commit Message格式
```
type(scope): description

[optional body]

[optional footer]
```

类型：
- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `style`: 代码格式
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建或工具相关

### Pull Request规范
- 清晰的标题和描述
- 关联相关Issues
- 包含测试用例
- 更新相关文档

## 🔍 代码审查

### 审查要点
- 代码质量和风格
- 功能正确性
- 性能影响
- 安全性考虑
- 文档完整性

### 审查流程
1. 自动化检查通过
2. 至少一个维护者审查
3. 讨论和修改
4. 最终批准和合并

## 🏆 贡献者认可

- 在README中添加贡献者列表
- 发布说明中感谢贡献者
- 优秀贡献者邀请成为维护者

## 📞 联系方式

- GitHub Issues: 技术问题和建议
- GitHub Discussions: 一般讨论
- Email: [项目邮箱]

## 📄 许可证

通过贡献代码，您同意您的贡献将在 [Apache 2.0](LICENSE) 许可证下发布。

---

感谢您的贡献！🎉
