# run_memorize.py 使用文档

## 概述

`run_memorize.py` 是一个群聊记忆存储脚本，用于读取符合 `GroupChatFormat` 格式的 JSON 文件，并将其转换后存储到记忆系统中。

## 功能特性

- ✅ 读取并验证 GroupChatFormat 格式的 JSON 文件
- ✅ 自动转换为 memorize 接口所需的格式
- ✅ 支持直接调用 memory_manager（推荐）
- ✅ 支持通过 HTTP API 调用
- ✅ 提供格式验证模式
- ✅ 详细的日志输出

## 使用方法

### 1. 基本用法（推荐）

使用 `bootstrap.py` 启动脚本，直接调用 memory_manager：

```bash
python src/bootstrap.py src/run_memorize.py --input data/group_chat.json
```

### 2. 使用 HTTP API

如果记忆服务已经在运行，可以通过 HTTP API 调用：

```bash
python src/bootstrap.py src/run_memorize.py \
  --input data/group_chat.json \
  --api-url http://localhost:1995/api/v2/agentic/memorize
```

### 3. 仅验证格式

验证输入文件格式是否正确，不执行存储：

```bash
python src/bootstrap.py src/run_memorize.py \
  --input data/group_chat.json \
  --validate-only
```

## 命令行参数

| 参数 | 必需 | 说明 |
|------|------|------|
| `--input` | 是 | 输入的群聊 JSON 文件路径（GroupChatFormat 格式） |
| `--api-url` | 否 | memorize API 地址（如果不提供则直接调用 memory_manager） |
| `--validate-only` | 否 | 仅验证输入文件格式，不执行存储 |

## 输入文件格式

输入文件必须符合 `GroupChatFormat` 规范，详见 `data_format/group_chat/group_chat_format.py`。

### 格式示例

```json
{
  "version": "1.0.0",
  "conversation_meta": {
    "name": "智能销售助手项目组",
    "description": "智能销售助手项目的开发讨论群",
    "group_id": "group_sales_ai_2025",
    "created_at": "2025-02-01T09:00:00+08:00",
    "default_timezone": "Asia/Shanghai",
    "user_details": {
      "user_101": {
        "full_name": "Alex",
        "role": "技术负责人"
      },
      "user_102": {
        "full_name": "Betty",
        "role": "产品经理"
      }
    },
    "tags": ["AI", "销售", "项目开发"]
  },
  "conversation_list": [
    {
      "message_id": "msg_001",
      "create_time": "2025-02-01T10:00:00+08:00",
      "sender": "user_101",
      "sender_name": "Alex",
      "type": "text",
      "content": "大家早，今天讨论一下项目进度",
      "refer_list": []
    }
  ]
}
```

## 处理流程

脚本执行以下步骤：

1. **格式验证**
   - 读取输入 JSON 文件
   - 验证是否符合 GroupChatFormat 规范
   - 输出数据统计信息

2. **格式转换**
   - 使用 `convert_group_chat_format_to_memorize_input()` 转换格式
   - 提取群组信息（group_id, group_name）
   - 转换消息列表

3. **构建请求**
   - 使用 `_handle_conversation_format()` 构建 MemorizeRequest
   - 设置历史消息和新消息的分割点（默认 80%）

4. **存储记忆**
   - 调用 `memory_manager.memorize()` 或 HTTP API
   - 返回存储结果

## 输出示例

### 成功输出

```
🚀 群聊记忆存储脚本
======================================================================
📄 输入文件: /path/to/group_chat.json
🌐 API地址: 直接调用
🔍 验证模式: 否
======================================================================
======================================================================
验证输入文件格式
======================================================================
正在读取文件: /path/to/group_chat.json
正在验证 GroupChatFormat 格式...
✓ 格式验证通过！

=== 数据统计 ===
格式版本: 1.0.0
群聊名称: 智能销售助手项目组
群聊ID: group_sales_ai_2025
用户数量: 5
消息数量: 8
时间范围: 2025-02-01T10:00:00+08:00 ~ 2025-02-01T10:05:00+08:00

======================================================================
步骤1: 读取并转换群聊数据
======================================================================
正在读取文件: /path/to/group_chat.json
正在转换为 memorize 接口格式...
✓ 转换完成！
  - 消息数量: 8
  - 群组ID: group_sales_ai_2025
  - 群组名称: 智能销售助手项目组

======================================================================
步骤2: 构建 MemorizeRequest
======================================================================
✓ MemorizeRequest 构建完成！
  - 历史消息数: 6
  - 新消息数: 2
  - 数据类型: Conversation
  - 群组ID: group_sales_ai_2025
  - 群组名称: 智能销售助手项目组

======================================================================
步骤3: 存储记忆
======================================================================
正在调用 memory_manager.memorize()...

✓ 记忆存储成功！共保存 3 条记忆

=== 存储的记忆摘要 ===
1. 类型: episode_summary
   摘要: 团队讨论了智能销售助手项目的开发进度和技术方案...
2. 类型: profile
   摘要: Alex 是技术负责人，负责技术架构设计...
3. 类型: group_profile
   摘要: 智能销售助手项目组是一个技术团队...

======================================================================
✓ 处理完成！
======================================================================
```

## 错误处理

### 文件不存在

```
错误: 输入文件不存在: /path/to/file.json
```

### 格式验证失败

```
✗ 格式验证失败！
请确保输入文件符合 GroupChatFormat 规范
```

### JSON 解析错误

```
✗ JSON 解析失败: Expecting value: line 1 column 1 (char 0)
```

## 与 full_pipeline.py 的区别

| 特性 | run_memorize.py | full_pipeline.py |
|------|-----------------|------------------|
| 输入格式 | GroupChatFormat（标准格式） | 自定义对话格式 |
| 转换逻辑 | 使用 group_chat.py 转换器 | 自定义转换逻辑 |
| 调用方式 | 直接调用或 HTTP | HTTP + subprocess |
| 使用场景 | 通用群聊记忆存储 | 特定评估流程 |
| 复杂度 | 简单，单步处理 | 复杂，多步 Pipeline |

## 开发说明

### 核心依赖

- `infra_layer.adapters.input.api.mapper.group_chat_converter`: 格式转换
- `agentic_layer.memory_manager`: 记忆管理器
- `agentic_layer.converter`: 请求转换
- `core.observation.logger`: 日志工具

### 扩展建议

1. **批量处理**: 支持处理目录下的多个文件
2. **进度显示**: 添加进度条显示处理状态
3. **错误重试**: 添加失败重试机制
4. **结果导出**: 将存储结果导出为 JSON 文件
5. **增量更新**: 支持基于已有记忆的增量更新

## 常见问题

### Q1: 为什么推荐使用 bootstrap.py 启动？

A: `bootstrap.py` 会自动处理：
- Python 路径设置
- 环境变量加载
- 依赖注入容器初始化
- Mock 模式支持

这样可以确保脚本在完整的应用上下文中运行。

### Q2: 直接调用和 HTTP 调用有什么区别？

A: 
- **直接调用**: 在同一进程中调用 memory_manager，速度快，适合开发测试
- **HTTP 调用**: 通过网络调用独立运行的服务，适合生产环境

### Q3: 如何调整历史消息和新消息的分割比例？

A: 目前默认使用 80% 作为历史消息。如需调整，可以在调用 `_handle_conversation_format()` 时传入 `split_ratio` 参数。

## 参考资料

- [GroupChatFormat 格式定义](../../data_format/group_chat/group_chat_format.py)
- [Agentic V2 API 文档](../api_docs/agentic_v2_api.md)
- [Bootstrap 使用文档](./bootstrap_usage.md)

