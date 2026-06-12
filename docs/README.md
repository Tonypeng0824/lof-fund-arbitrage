# 套利渠道追踪 - GitHub Pages

自动每日更新的套利渠道汇总页。部署到 GitHub Pages 后可通过自定义域名访问。

## 文件结构

```
github-pages/
├── index.html          # 每日更新的套利报告
├── CNAME               # 自定义域名（把域名填进去）
└── README.md           # 本文件
```

## 自定义域名配置

1. 编辑 `CNAME` 文件，填入你的域名（如 `taoli.yourdomain.com`）
2. 在你的域名DNS服务商添加CNAME记录：
   - 类型: CNAME
   - 主机记录: taoli（或你想用的子域名）
   - 记录值: `<你的GitHub用户名>.github.io`
3. 等DNS生效（通常几分钟到几小时）

## 更新方式

每日本地脚本运行后自动 `git push`，GitHub Pages 自动构建发布。
