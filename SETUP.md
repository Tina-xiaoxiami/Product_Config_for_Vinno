# 产品配置管理系统 - Windows 安装指南

## 环境准备（一次性）

### 1. 安装 Python

下载地址：https://www.python.org/downloads/

- 选择 **Python 3.10 或更高版本**
- 安装时 **勾选 "Add Python to PATH"**（非常重要）

安装完成后打开命令提示符（Win+R 输入 `cmd`），验证：

```
python --version
```

### 2. 安装 Node.js

下载地址：https://nodejs.org/

- 选择 **LTS 版本**（长期支持版）
- 一路默认安装即可

验证：

```
node --version
npm --version
```

## 项目初始化（一次性）

打开命令提示符，进入项目目录：

```
cd 项目所在路径\产品配置管理系统
```

### 3. 安装后端依赖

```
cd backend
pip install -r requirements.txt
cd ..
```

### 4. 安装前端依赖

```
cd frontend
npm install
cd ..
```

### 5. 数据库

系统使用 SQLite 本地文件数据库，首次启动会自动创建空数据库。

如需使用现有数据，将 `product_config.db` 文件复制到 `backend/` 目录下即可。

## 日常使用

- **启动**：双击 `start.bat`，浏览器会自动打开
- **停止**：双击 `stop.bat`

启动后访问：http://localhost:3006

产品知识库：http://localhost:3006/knowledge

- 功能主数据以 IPN 为唯一身份，支持中英文主名、备用名和研发名搜索。
- PDF 和图片可在页面内预览，Word/Excel 通过“打开原文”访问。
- 原始资料不会复制到数据库；运行系统的电脑需保持原文件路径可用。
