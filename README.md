# Kronos A股自动预测

每天 8:00 北京时间自动运行 Kronos-small 模型，预测 A 股未来 5 日价格。

## 工作原理

```
GitHub Actions (每天 8:00 CST, 免费)
  │  拉腾讯财经 A 股日线
  │  Kronos-small CPU 推理
  │  生成 latest.json → git push
  ▼
Termux (cron 8:15 CST)
  │  git pull
  │  kronos_reader.py 读取
  ▼
Hermes 研究员盘前简报
  🤖+🔬 双确认 / 分歧标注
```

## 每日自动执行

- **调度**: 工作日 8:00 CST (0:00 UTC)
- **运行环境**: GitHub Actions ubuntu-latest (CPU, 免费)
- **预测标的**: 中科曙光 / 艾华集团 / 汇川技术
- **输出**: `latest.json` (直接推送到仓库)

## 手动触发

在 GitHub repo → Actions → "Kronos A股每日预测" → Run workflow

## 本地使用

```bash
# 克隆仓库
git clone <this-repo-url> kronos_predictions

# 读取预测
python3 ~/.hermes/scripts/kronos_reader.py --file kronos_predictions/latest.json
```
