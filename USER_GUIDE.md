---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: e484fdc44aa47425620c0c086e7e2216_4c02446dd2e311f1992e525400638852
    ReservedCode1: 53M2ojwSmqCfCLK6tr5y0Myu1XO8kYfD63yLVLV9yxupvFaVEao5hhvrO7mrtjhbskQVzyDag7vCKVTZTvn3dWSP0WXFCn7/UNnBYrUg5WwnaiMehtj2j9zsH5k9W658OS64N9V4tkpMGpCY0DN9EXTrAHEIco4YDoUgrrlHCEOVBNj53n1JPJr6KJQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: e484fdc44aa47425620c0c086e7e2216_4c02446dd2e311f1992e525400638852
    ReservedCode2: 53M2ojwSmqCfCLK6tr5y0Myu1XO8kYfD63yLVLV9yxupvFaVEao5hhvrO7mrtjhbskQVzyDag7vCKVTZTvn3dWSP0WXFCn7/UNnBYrUg5WwnaiMehtj2j9zsH5k9W658OS64N9V4tkpMGpCY0DN9EXTrAHEIco4YDoUgrrlHCEOVBNj53n1JPJr6KJQ=
---

# 运行与使用教程（度假租赁客服机器人）

> 本教程面向**不会写代码的客户/运营人员**。跟着步骤做即可完成安装、配置、启动，并用 **Excel（或任意表格软件）** 维护房源和预订，全程不需要碰代码。

---

## 1. 这套系统是什么

这是一个 **Telegram 客服机器人**：客人在 Telegram 里给机器人发消息，机器人会弹出服务菜单（1 预定 / 2 查询房源 / 3 修改 / 4 人工处理），客人选数字后机器人自动处理。

对运营方来说，核心只有 **两个表格文件**：

| 文件 | 作用 | 谁维护 |
|---|---|---|
| `properties.csv` | 房源表：每行一套房源（价格、人数、房态等） | 你用 Excel 维护 |
| `bookings.csv` | 预订表：每行一条预订记录 | 机器人自动写，也可手工编辑 |

**最大的好处**：表格保存后**立即生效**。你在 Excel 里保存房源表，客人下一秒钟查询就是最新数据，**不用改代码、不用重启机器人**。

---

## 2. 项目文件说明

| 文件 | 作用 | 需要改吗 |
|---|---|---|
| `bot.py` | 机器人主程序（启动入口） | 一般不用动；配置 Token 时改一次 |
| `properties.csv` | 房源表（**最重要**） | ✅ 用 Excel 维护 |
| `bookings.csv` | 预订表 | ✅ 可手工编辑 |
| `properties.json` | 旧版房源数据（**备用**） | 不用动 |
| `property_store.py` | 读取表格的程序 | 不用动 |
| `classify.py` | 识别客人意图的程序 | 不用动 |
| `keywords.json` | 关键词配置（可扩展识别词） | 可选 |
| `storage.py` | 工单记录（`tickets.csv`） | 不用动 |
| `clickup_client.py` | ClickUp 对接（可选） | 不用动 |
| `restart.sh` | 一键重启脚本 | 不用动 |
| `USER_GUIDE.md` | 本文档 | — |

---

## 3. 第一次运行：环境准备

### 3.1 安装 Python

**macOS：**
1. 打开浏览器访问 <https://www.python.org/downloads/>，下载 macOS 安装包。
2. 双击安装，一路“继续”即可。
3. 打开“终端”（Launchpad 搜索“终端”），输入下面命令回车，看到版本号即成功：

```bash
python3 --version
```

**Windows：**
1. 访问 <https://www.python.org/downloads/> 下载安装包。
2. 安装时**务必勾选 “Add Python to PATH”**。
3. 打开“命令提示符”，输入 `python --version` 验证。

> 本项目已自带虚拟环境 `.venv`，如果你直接用项目内终端执行命令，依赖通常已经就绪。

### 3.2 安装依赖

打开终端，进入项目目录：

```bash
cd /Users/joeyweng/Desktop/vacation_rental_ops
```

安装依赖（只需执行一次）：

```bash
python3 -m pip install python-telegram-bot requests
```

### 3.3 配置 Telegram Bot Token（必做）

机器人必须有一个 Token 才能连上 Telegram。

1. 在 Telegram 中搜索 **@BotFather**，给它发 `/newbot`。
2. 按提示给你的机器人起一个显示名称和用户名（如 `my_vacation_bot`）。
3. BotFather 会返回一串 **Token**，形如：`123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxx`。
4. 用任意文本编辑器打开项目根目录下的 `.env`（若不存在，先复制模板：`cp .env.example .env`）。
5. 找到这一行，把 `=` 后面替换成你自己的 Token：

```env
TELEGRAM_TOKEN=123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxx
```

6. 保存文件并重启机器人，Token 即生效。

> 注意：Token 相当于密码，不要发给别人，也不要提交到公开仓库。本项目 `.gitignore` 已排除含敏感信息的文件。

### 3.4 配置 ClickUp（可选，不配置也能用）

如果不使用 ClickUp，跳过本节即可——机器人会自动降级为“仅 CSV 记录”模式，所有功能正常。

如需对接：编辑 `clickup_client.py`，把文件里 `CLICKUP_TOKEN` 和 `CLICKUP_LIST_ID` 换成你自己的（获取方式见该文件内注释）。

---

## 4. 启动与停止

### 4.1 启动

在项目目录执行：

```bash
python3 bot.py
```

看到下面这行就说明启动成功：

```
Bot started, listening for messages... (Ctrl+C to stop)
```

> 启动后请保持终端窗口开着（不要关闭）。关闭终端 = 停止机器人。

### 4.2 一键重启（推荐）

项目已提供 `restart.sh`，它会自动停掉旧进程并启动新进程：

```bash
cd /Users/joeyweng/Desktop/vacation_rental_ops
./restart.sh
```

看到 `Bot restarted successfully. PID: ...` 即成功。

### 4.3 手动停止

- 前台运行时：在终端按 `Ctrl + C`。
- 后台运行时：

```bash
pkill -f "python3 bot.py"
```

### 4.4 查看是否在运行

```bash
pgrep -f "python3 bot.py"
```

有 PID 数字输出 = 正在运行；无输出 = 未运行。

---

## 5. 用表格录入房源（免写代码）

### 5.1 打开房源表

1. 找到项目目录下的 **`properties.csv`**。
2. **右键 → 打开方式 → Excel（或 Numbers / WPS 表格）**。
3. 文件自带 UTF-8 编码标记（BOM），Excel 打开**不会乱码**。

### 5.2 字段说明（表头含义）

| 列名 | 含义 | 填写示例 | 必填 |
|---|---|---|---|
| `property_id` | 房源编号（唯一，客人用它预订） | `AD-101` | ✅ |
| `name` | 房源名称（显示给客人） | 海景公寓 | ✅ |
| `address` | 地址（仅内部参考） | 12 Marina Road, Beach Town | 可空 |
| `price_per_night` | 每晚价格（数字） | `1280` | ✅ |
| `bedrooms` | 卧室数量（数字） | `2` | ✅ |
| `max_guests` | 最多可住人数（数字） | `4` | ✅ |
| `amenities` | 设施清单，用**分号 `;`** 分隔 | `WiFi;空调;阳台` | 可空 |
| `status` | 房态：`available`=可入住 / `occupied`=已入住 | `available` | ✅ |
| `total_units` | **总间数**（该房型共有几间房，≥1） | `3` | ✅ |
| `available_units` | **当前可订间数**（剩余几间可订，0~总间数） | `2` | ✅ |

> - `status` 只能填两个词：`available`（可入住）或 `occupied`（已入住），注意拼写，不要加中文。
> - **库存字段（推荐必填）**：`total_units` 填该房型总间数，`available_units` 填当前剩余可订间数。客人每次成功预订，机器人会自动把 `available_units` 减 1（或减去预订间数）；取消订单会自动回补。**你在 Excel 里直接改 `available_units` 即可实时调整库存**（例如手动补一间、修正误操作），保存后立即生效，无需重启。
> - **旧格式兼容**：如果某行没有 `total_units` / `available_units` 两列，机器人自动按“总 1 间 / 可订 1 间”处理，不会报错。

### 5.3 新增一套房源

在 Excel 中**新起一行**，把各列填好，然后保存（`Ctrl+S` / `Command+S`）。示例：

| property_id | name | address | price_per_night | bedrooms | max_guests | amenities | total_units | available_units | status |
|---|---|---|---|---|---|---|---|---|---|
| AD-101 | Seaview Apartment 海景公寓 | 12 Marina Road, Beach Town | 1280 | 2 | 4 | WiFi;空调;阳台;海景 | 1 | 1 | available |
| AD-1475 | Sunny Villa 阳光别墅 | 88 Hillcrest Ave, Hillside | 2300 | 3 | 6 | WiFi;私人泳池;烧烤;停车位 | 1 | 1 | available |
| AD-203 | Cozy Studio 温馨单间 | 3 Lantern Lane, Old Town | 680 | 1 | 2 | WiFi;小厨房 | 1 | 1 | occupied |
| AD-301 | Garden Cottage 花园小屋 | 45 Orchard Lane, Riverside | 980 | 2 | 3 | WiFi;花园景;壁炉 | 2 | 2 | available |
| AD-302 | Penthouse Suite 顶层套房 | 200 Sky Tower, Downtown | 3200 | 3 | 6 | WiFi;屋顶露台;按摩浴缸;城市景观 | 1 | 1 | available |
| AD-303 | Lakeview Cabin 湖景木屋 | 7 Lake Shore Drive, Pine Valley | 1450 | 2 | 4 | WiFi;湖景;皮划艇;烧烤 | 3 | 3 | available |
| AD-304 | Modern Loft 现代Loft | 56 Factory Street, Arts District | 1100 | 1 | 2 | WiFi;智能电视;健身房 | 2 | 1 | available |
| AD-305 | Beachfront Bungalow 海滨平房 | 2 Palm Beach Road, Coastline | 1850 | 2 | 4 | WiFi;海滩通道;冲浪板;阳台 | 2 | 2 | available |
| AD-306 | Mountain Retreat 山间度假屋 | 12 Summit Trail, Alpine | 1680 | 3 | 6 | WiFi;热水浴缸;山景;登山装备 | 2 | 2 | available |
| AD-307 | City Studio 城市单间 | 88 Metro Plaza, CBD | 750 | 1 | 2 | WiFi;洗衣机;近地铁 | 4 | 4 | available |
| AD-308 | Family Villa 家庭别墅 | 25 Green Park Road, Suburb | 2600 | 4 | 8 | WiFi;私人花园;儿童游乐区;停车位 | 1 | 1 | available |
| AD-309 | Harbor View House 港景之家 | 16 Pier Street, Harbor | 1550 | 3 | 5 | WiFi;港景;阳台;停车位 | 2 | 2 | available |
| AD-310 | Boutique Room 精品客房 | 9 Silk Lane, Heritage Quarter | 820 | 1 | 2 | WiFi;迷你吧;历史装饰 | 3 | 3 | available |

### 5.4 修改 / 停售房源

- 改价格、人数：直接改单元格后保存。
- **调整库存**：改 `available_units`（剩余可订间数）即可，保存后实时生效，无需重启。
- 停售：把 `status` 改成 `occupied`（或把 `available_units` 改成 `0`，此时客人预订会收到“该房型已订满”提示）。
- 删除房源：删掉整行后保存。

### 5.5 保存后生效（重点）

**保存即生效，无需重启、无需改代码。** 客人再查询时，机器人读到的就是最新表格内容。

> 注意：请直接保存到原文件 `properties.csv`，不要“另存为”成 `.xlsx` 或改名；机器人只认这个文件名。

---

## 6. 预订记录与房态联动

### 6.1 客人通过 Telegram 预订

客人发“我要订 AD-101” → 机器人回菜单 → 客人回复 `1`：

- 机器人自动在 **`bookings.csv`** 里新增一条预订记录；
- 同时把 **`properties.csv`** 中该房源 `available_units` 自动**减 1**（客人在消息里说“订 2 间”则减 2，默认按 1 间）；
- 查询该房源时，显示“剩余 X 间”；
- 当 `available_units` 为 0 时，客人再预订会收到“该房型已订满”的提示，不会产生超卖；
- 客人在“修改房源（3）”菜单里选择取消时，机器人会自动把间数**回补**到 `available_units`（最多回到 `total_units`，不会超总间数）。

### 6.2 bookings.csv 字段说明

| 列名 | 含义 | 说明 |
|---|---|---|
| `booking_id` | 订单号 | 机器人自动生成（如 `BK-20261028-0001`） |
| `property_id` | 房源编号 | 对应 `properties.csv` 的编号 |
| `guest_name` | 客人姓名 | 机器人自动取 Telegram 昵称，可手工修改 |
| `check_in` | 入住日期 | 格式 `YYYY-MM-DD`，可空 |
| `check_out` | 退房日期 | 格式 `YYYY-MM-DD`，可空 |
| `status` | 订单状态 | 如 `confirmed`，可自定义 |
| `created_at` | 创建时间 | 机器人自动填写 |

### 6.3 手工新增 / 修改预订

用 Excel 打开 `bookings.csv`，新增一行或改单元格后保存即可。机器人下次读取就是最新记录。

---

## 7. 日常使用（操作员 / 客服）

在 Telegram 里和机器人对话：

| 客人说 | 机器人反应 |
|---|---|
| 发送 `/start` | 欢迎语 + 服务菜单 |
| 发送“还有没有房间” | 回菜单，回复 `2` 查看可入住房源 |
| 发送“我要订 AD-101” | 回菜单，回复 `1` 完成预订（写入预订表 + 房态联动） |
| 发送“我要改 AD-1475 的预订” | 回菜单，回复 `3` 记录修改工单 |
| 发送“房间漏水了” | 回菜单，回复 `3` 记录投诉（高优先级） |
| 发送“帮我转人工” | 回菜单，回复 `4` 转人工处理 |
| 发送 `/summary` | 查看已记录工单统计 |
| 发送 `/list_properties` | 查看全部房源及房态 |

> 机器人支持中英文。客人回数字（1/2/3/4）时，回复语言会沿用上一句的语言。

### 7.1 房东自助：添加房源（菜单 5）

只有 **`.env` 中配置了 `ADMIN_CHAT_ID`** 的房东账号能看到并操作「5 添加房源 / 6 删除房源」；普通客户看不到这两项，即使回复 `5` 或 `6` 也会被提示“仅房东可操作该功能”。

**操作步骤：**
1. 在 Telegram 中给机器人发任意消息，菜单会显示 `5 = 添加房源`。
2. 回复 **`5`**，机器人提示输入格式。
3. 按以下格式发送新房源（用 **`|`** 分隔 5 项）：

```
房源ID|名称|描述|价格|总间数
AD-999|海景豪华房|带阳台海景|1500|3
```

4. 校验规则：
   - 房源 ID 不能为空，且不能与已有 ID 重复；
   - 价格必须为正数；
   - 总间数必须为整数且 ≥1；
   - 5 个字段缺一不可。
5. 格式正确 → 机器人写入 `properties.csv` 并回显房源卡片；格式错误 → 机器人给出示例提示重试，**对话不中断**；回复「取消」可退出添加。

> 说明：`价格`、`总间数` 都填数字，不要带货币符号或单位。

### 7.2 房东自助：删除房源（菜单 6）

1. 回复 **`6`**，机器人提示输入房源 ID。
2. 发送要删除的房源 ID（如 `AD-203`）。
3. 机器人回显该房源当前信息（名称、价格、总间数、剩余间数），并要求确认。
4. 回复 **`Y`** 确认删除，或 **`N`** 取消；回复其他内容会再次提示 Y/N。
5. 确认后机器人删除 `properties.csv` 中该房源行；**该房源关联的历史预订记录保留在 `bookings.csv` 中，不会被删除**。

> 提示：删除房源前建议先在 Excel 里备份一份 `properties.csv`。

---

## 8. 常见问题排查

| 现象 | 可能原因 | 解决办法 |
|---|---|---|
| 机器人收不到 / 不回消息 | Token 配置错误 | 重新核对 `bot.py` 中 `TOKEN`，确认没有多余空格 |
| 启动时报错 `ModuleNotFoundError` | 依赖未装 | 执行 `python3 -m pip install python-telegram-bot requests` |
| 端口/进程被占用 | 旧进程还在跑 | 执行 `pkill -f "python3 bot.py"` 后重新启动 |
| 改了表格但查询没变 | 保存成了新文件（.xlsx） | 确认直接保存为原 `properties.csv`（UTF-8 编码） |
| Excel 打开 CSV 乱码 | 文件被另存时丢了 BOM | 用“另存为”→ 编码选 **UTF-8**（或 UTF-8 with BOM）重新保存 |
| 房态不联动 | `status` 字段拼写错误 | 只填 `available` 或 `occupied` |
| 查询报“未找到房源” | 编号不匹配 | 确认 `properties.csv` 中 `property_id` 存在，且客人提供的是 AD-xxx 格式 |
| ClickUp 没有新任务 | 未配置或 Token 失效 | 属可选功能，不影响聊天；检查 `clickup_client.py` 配置 |
| 想恢复出厂数据 | 表格被改乱 | 可用同目录 `properties.json` 中数据恢复，或参考第 5.3 节示例重建 |

---

## 9. 数据与安全提示

- `bookings.csv`、`properties.csv`、`tickets.csv` 是业务数据，**请定期备份**（复制一份到别的文件夹即可）。
- `clickup_client.py`、`llm_reply.py`、`.env` 含敏感配置，**不要发给别人、不要上传公开仓库**（`.gitignore` 已自动排除）。
- 修改表格前建议先复制一份备份。

### 9.1 管理员通知转发（可选）

当客户选择「4. 人工处理」、发送投诉或转人工类消息时，bot 可以把客户消息和简要上下文（客户用户名 / chat_id / 消息原文 / 意图 / 房源编号）转发给指定管理员。该功能默认关闭，需要按以下步骤开启：

1. **获取管理员的 chat_id**
   - 在 Telegram 中搜索并打开机器人 **@userinfobot**
   - 点击「Start / 开始」，它会直接回复你的 `Id`（一串数字，例如 `123456789`）
   - 用同样的方式让管理员也获取自己的 `Id`（转发目标就是这个数字）
2. **填入 .env**
   - 编辑项目根目录的 `.env` 文件（没有就新建一个）
   - 找到 `ADMIN_CHAT_ID` 行，把管理员数字填进去：
     ```
     ADMIN_CHAT_ID=123456789
     ```
3. **重启 bot**（运行 `./restart.sh`）使其生效。
4. **验证**：以客户身份选择「4. 人工处理」，管理员会收到转发通知；如果 `ADMIN_CHAT_ID` 留空，客户仍会收到正常提示（如“已记录，我们会尽快处理”），功能不受影响。

> 注意：`ADMIN_CHAT_ID` 为空或未配置时转发自动关闭，不报错；该值仅存于 `.env`，不会写入任何代码文件。

---

*祝你使用愉快。如遇到本文档未覆盖的问题，请联系维护方协助排查。*
