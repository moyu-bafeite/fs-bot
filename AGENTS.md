# 项目编码规范 — fs-bot

## 语言要求

- 所有回答、注释、commit message、PR 描述均使用**简体中文**
- 代码标识符（变量名、函数名、类名）使用**英文**
- 错误信息和日志可使用英文

## 项目技术栈

- **语言**: Python 3.12+
- **包管理**: uv（禁止使用 pip）
- **代码风格**: ruff（linter + formatter）
- **类型检查**: pyright

## 编码规范

### Python 风格

- 使用现代 Python 3.12+ 语法：内置泛型（`list[str]`）、联合类型（`str | None`）
- 禁止使用 `typing.List`、`typing.Dict`、`typing.Optional` 等旧式导入
- 所有函数参数必须有类型注解，局部变量可依赖类型推断
- 空容器需显式标注类型：`items: list[str] = []`

### 命名约定

- 变量、函数：`snake_case`
- 类：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`
- 私有成员：`_leading_underscore`

### 代码组织

- 每个模块保持单一职责
- 导入顺序：标准库 → 第三方库 → 本地模块（ruff isort 自动处理）
- 函数尽量保持简短，避免过深嵌套（max 3 层）

### 错误处理

- 使用具体的异常类型，避免裸 `except Exception`
- 在系统边界（用户输入、外部 API）进行校验
- 内部代码信任调用方，不过度防御

### 注释

- 默认不写注释，代码应自解释
- 仅在以下情况添加注释：
  - 隐藏的约束或业务规则
  - 绕过特定 bug 的 workaround
  - 反直觉的行为

## 工作流程

### 运行命令

```bash
# 安装依赖
uv add <package>

# 运行脚本
uv run python main.py

# 代码检查
uv run ruff check --fix .
uv run ruff format .

# 类型检查
uv run pyright .
```

### Git 规范

- Commit message 使用中文，格式：`<类型>: <简述>`
- 类型：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`
- 示例：`feat: 添加用户认证模块`

## 回答风格

- 简洁直接，不废话
- 不使用 emoji（除非用户明确要求）
- 引用代码时附带 `文件路径:行号` 方便定位
- 代码块标注语言类型
- 完成任务后用一两句话总结变更内容和后续步骤
