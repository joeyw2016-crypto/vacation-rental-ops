# 录屏演示清单（2 核心功能 · 3-4 分钟）

目标：Upwork 度假租赁 AI 自动化案例演示。画面=Telegram 对话 + 总览表，配音=英文 AI 配音（en-US），时长约 3:30。

---

## 开场（0:00-0:15）

- 画面：标题卡 "Vacation Rental Ops Bot — AI Automation Demo"
- 配音：A Telegram chatbot for vacation rental operations. Two core features: guest self-service booking, and single-table host maintenance.

---

## 功能一：客户自助查房 + 预订（0:15-1:45）

| 步骤 | 画面操作 | 配音 |
|---|---|---|
| 1 | 打开 Telegram，进入 @vacation_rental_demo_bot | A guest asks for availability. |
| 2 | 发送：Do you have any rooms available? | The bot understands the request instantly. |
| 3 | bot 回复 5 条房源编号列表（1) AD-101 ...） | It lists all available properties in a numbered menu. |
| 4 | 回复数字 1（选 AD-101 海景公寓） | The guest picks a room with a single number. |
| 5 | bot 询问确认预订 | The bot asks for confirmation. |
| 6 | 回复 1 确认 | One tap to confirm. |
| 7 | bot 返回预订成功信息 | The booking is confirmed instantly. |
| 8 | 切换到 vacation_rental_overview.xlsx：预订 Sheet 出现新预订行；房源 Sheet AD-101 库存 1→0 | Every booking is automatically recorded in the overview table, and inventory is updated in real time. |

---

## 功能二：房东一张表维护（1:45-3:15）

| 步骤 | 画面操作 | 配音 |
|---|---|---|
| 1 | 总览表预订 Sheet：把该预订 status 改为 cancelled（退房） | When a guest checks out, the host simply changes the status in the spreadsheet. |
| 2 | 保存文件 | Save — that's it. |
| 3 | 回到 Telegram，发任意消息（如：Do you have any rooms available?） | The next message triggers an automatic sync. |
| 4 | bot 回复房源列表：AD-101 重新可订，库存回补为 1 | The room is back on the market with inventory restored automatically. |
| 5 | （加时展示）总览表房源 Sheet 新增一行房源 → 保存 → 发消息 → bot 查房列表出现新房源 | Adding a property is just one row in the spreadsheet. |

---

## 收尾（3:15-3:40）

- 画面：项目/技术栈小结页（Telegram Bot · Python · Spreadsheet sync · 24/7 automation）
- 配音：Guests get instant self-service answers around the clock. The host manages everything from a single spreadsheet — no code, no manual inventory work. Fully automated, ready to extend.

---

## 说明

- 语言：Telegram 对话与配音默认英文（面向 Upwork 客户）；如需中文可切换。
- 演示前数据：5 条房源、0 预订（已就绪）。
- 录屏方式：脚本驱动 bot 对话 + 静默录屏 + AI 英文配音合成（方案A）。
