# 发布到 Streamlit Community Cloud（公网链接）

把本地交易系统发布成公网可访问的网页应用，约 10 分钟，免费。

## 原理

Streamlit Community Cloud 会从你的 GitHub 仓库拉取代码，在云端自动安装
`requirements.txt` 中的依赖并启动 `main.py`，最终给你一个
`https://<应用名>.streamlit.app` 的公网链接，任何设备都能打开。

> 云端运行说明：自选股池与复盘数据保存在**云端服务器**自己的 `data/` 目录下，
> 与本地 `data/` 互不影响（本地仍是 `localhost:28618`）。云端网络通常可直连
> 东方财富接口，AkShare 首选源会自动生效。

## 路径 A：GitHub 网页上传（无需安装任何软件，推荐）

1. **注册/登录 GitHub**
   打开 https://github.com → 右上角 Sign up（已有账号则 Sign in）。

2. **新建仓库**
   - 右上角 `+` → New repository
   - Repository name 填：`trading-system-py`
   - 选择 **Public**（Streamlit 免费版需要公开仓库）
   - 其他默认，点 **Create repository**

3. **上传工程文件**
   - 在新建的仓库页面点 **Add file → Upload files**
   - 把下面文件**夹与文件**拖进页面（从
     `C:\Users\chenbo\Doubao\chats\2026-10-05\new-chat\trading-system-py\` 拖入）：

     ```
     main.py
     config.py
     requirements.txt
     README.md
     .gitignore
     .streamlit/            # 整个文件夹（含 config.toml）
     pages/                 # 整个文件夹（1-6 六个页面）
     data/market_data.py
     data/__init__.py
     analysis/              # 整个文件夹（6 个 py）
     tools/smoke_test.py    # 可选
     ```

     ⚠️ **不要上传**：`data/reviews.json`、`data/watchlist.json`（本地数据，
     云端会自动重建）、`__pycache__` 文件夹。
   - 页面底部点 **Commit changes**

4. **部署到 Streamlit Cloud**
   - 打开 https://streamlit.io → 点 **Sign in** → 用 GitHub 账号授权登录
   - 点 **Create app → From existing repo**
   - Repository：选择 `你的账号/trading-system-py`
   - Branch：`main`；Main file path：`main.py`
   - App URL 会自动生成（如 `trading-system-py.streamlit.app`），点 **Deploy**
   - 首次部署需 5-10 分钟安装依赖（akshare 较大），页面提示 *"Building..."*
     属于正常，等状态变为 **Running** 即可
   - 完成后访问你的 `https://trading-system-py.streamlit.app`，就是公网版应用

## 路径 B：命令行推送（需先安装 Git）

1. 下载安装 Git：https://git-scm.com/download/win（一路默认）
2. 在本机打开 PowerShell，进入工程目录并初始化推送：

   ```powershell
   cd C:\Users\chenbo\Doubao\chats\2026-10-05\new-chat\trading-system-py
   git init
   git add .
   git commit -m "交易系统工作台 V2：自选股池/布林带/复盘对接"
   git branch -M main
   git remote add origin https://github.com/<你的账号>/trading-system-py.git
   git push -u origin main
   ```
   （push 时按提示登录 GitHub；`<你的账号>` 换成第 1 步注册的用户名）

3. 回到上方「部署到 Streamlit Cloud」步骤 4，同样操作。

## 后续更新

本地改完代码后，重新上传/推送覆盖同名文件，Streamlit Cloud 会自动重新部署
（Deploy 页面点 **Redeploy** 或等待自动更新）。

## 常见问题

| 现象 | 处理 |
|---|---|
| 部署后页面报错 | 打开应用，点页面底部 `Manage app` 查看 Logs；常见是依赖安装超时，点 Redeploy 重试一次 |
| App URL 被占用 | 部署时自动生成的 URL 冲突会提示，把 App URL 改个名字即可 |
| 云端数据与本地不同 | 正常，两套 `data/` 相互独立 |
