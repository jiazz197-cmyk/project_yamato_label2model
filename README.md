# label2model

基于 [Label Studio](https://github.com/HumanSignal/label-studio)（Apache-2.0）构建的数据标注与数据集生成平台。

## 致谢

本项目基于 [HumanSignal](https://humansignal.com/) 开源的 Label Studio 二次开发，保留了其核心标注、数据管理、导出和用户鉴权功能。感谢 Label Studio 团队的开源贡献。

- 原项目: https://github.com/HumanSignal/label-studio
- License: Apache-2.0

## 技术栈

- 后端: Django 5.1 + DRF + PostgreSQL + Redis + MinIO
- 前端: React 18 + TypeScript (Nx monorepo)

## 快速开始

### 前置条件

- Python 3.12 + Poetry >= 2.0
- Node.js + Yarn
- PostgreSQL / Redis / MinIO（中间件已在远程服务器部署）

### 1. 安装依赖

```bash
poetry install
cd web && yarn install --frozen-lockfile && cd ..
```

### 2. 构建前端

```bash
cd web && yarn build && cd ..
```

### 3. 数据库迁移

```bash
python label_studio/manage.py migrate
```

### 4. 收集静态文件

```bash
python label_studio/manage.py collectstatic --no-default-ignore
```

### 5. 创建超级用户

```bash
python label_studio/manage.py createsuperuser
```

### 6. 启动服务

```bash
python label_studio/manage.py runserver 0.0.0.0:8080
```

访问 http://localhost:8080

## 配置

所有配置通过项目根目录的 `.env` 文件管理，包括数据库、MinIO、Redis 连接信息。
