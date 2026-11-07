# 🦆 DIY 雙足鴨子機器人

自己動手做一隻像 **Microduck** 的雙足鴨子機器人：會用 AI 走路、會點頭跳舞，可以用手機、手把或 LINE 遙控。

> **為什麼不是直接照 Microduck 做？**
> Microduck（Pollen Robotics / Hugging Face，黃仁勳在 GTC 台上展示的那隻）**軟體**是開源的（Apache 2.0），
> 但目前沒有公開可以讓人自己組裝的機構圖、電路和零件清單（模擬用的 3D 模型是 CC BY-NC-SA，不能商用）。
> 它的前身 **Open Duck Mini v2** 是同一位工程師（Antoine Pirrone）做的社群專案，
> 3D 列印檔、零件清單、步行 AI 都公開，零件費不到 400 美元。所以這份程式**以 Open Duck Mini v2 的硬體為目標**，
> 也能直接用它公開的步行 AI 模型。

---

## 一、硬體要準備什麼

| 類別 | 零件 | 數量 | 參考價（新台幣） | 說明 |
|---|---|---|---|---|
| 🧠 主控 | Raspberry Pi Zero 2 W | 1 | ~600 | 跑控制程式和 AI 推論（50 Hz 夠用） |
| | microSD 卡 32 GB | 1 | ~250 | 裝 Raspberry Pi OS Lite 64-bit |
| 💪 馬達 | **Feetech STS3215（7.4 V 版）** 匯流排伺服馬達 | **14** | ~500 / 顆 | 每隻腳 5 顆、頭 4 顆。一定要買 **7.4 V** 版，跟電池電壓相符 |
| | 匯流排馬達轉接板（USB 轉 TTL），例如 Waveshare Bus Servo Adapter (A) | 1 | ~300 | Pi 透過 USB 控制 14 顆馬達 |
| 🧭 感測 | BNO055 IMU 模組（例如 Adafruit 4646） | 1 | ~1,200 | 感測傾斜和角速度，AI 走路一定要有 |
| | 微動開關 | 2 | ~50 | 裝在腳底，偵測有沒有踩到地 |
| 🔋 電源 | 2S 鋰電池 7.4 V（例如 2 顆 18650 + 電池盒，約 3000 mAh） | 1 | ~500 | 直接供電給馬達 |
| | 5 V 降壓模組（UBEC，3 A 以上） | 1 | ~150 | 7.4 V 降到 5 V 給 Pi 用 |
| | 電源開關、XT30 接頭、電線 | 1 組 | ~200 | |
| 🖨️ 機構 | 3D 列印件（PLA 約 1 kg；腳底用 TPU） | 1 套 | ~800 | 檔案在 Open Duck Mini 的 GitHub，沒有印表機可以找代印 |
| | 螺絲、軸承等小零件 | 1 組 | ~500 | **以官方 BOM 為準** |
| 🎮 選配 | Xbox / PS 藍牙手把 | 1 | — | 用 `--gamepad` 遙控 |
| | 喇叭（MAX98357 I²S 擴大機）、相機、LED | — | — | 之後想加表情、聲音再買 |

**總計大約 NT$12,000～14,000**（馬達佔一半）。
完整、最新的零件清單請看官方 BOM：<https://github.com/apirrone/Open_Duck_Mini>（v2 分支 README 裡的 Google Sheet 連結）。

**工具**：3D 印表機（或代印）、烙鐵、三用電表、六角起子、剝線鉗。

### 接線圖

```
 2S 電池 7.4V ──┬── 開關 ──┬──────────────► 馬達轉接板 V+ ──► 14 顆 STS3215（菊鏈串接）
                │          └── UBEC 5V ───► Pi Zero 2W 5V
                └── GND（全部共地）

 Pi Zero 2W
   USB  ──────────────► 馬達轉接板（出現 /dev/ttyACM0 或 /dev/ttyUSB0）
   GPIO2 (SDA) / GPIO3 (SCL) / 3.3V / GND ──► BNO055
   GPIO22 ──► 左腳開關 ──► GND
   GPIO27 ──► 右腳開關 ──► GND
```

### 馬達 ID 對照（一定要照這個設）

| 部位 | 髖 yaw | 髖 roll | 髖 pitch | 膝 | 踝 |
|---|---|---|---|---|---|
| 右腳 | 10 | 11 | 12 | 13 | 14 |
| 左腳 | 20 | 21 | 22 | 23 | 24 |

| 頭 | neck_pitch | head_pitch | head_yaw | head_roll |
|---|---|---|---|---|
| ID | 30 | 31 | 32 | 33 |

---

## 二、軟體架構

```
           ┌──────── 輸入 ─────────┐
 手機網頁 ─┤ HTTP API (server.py)  │
 LINE 機器人┤  ↑ app/handlers/duck.js│──► DuckController（controller.py，50 Hz 狀態機）
 藍牙手把 ─┤ gamepad.py            │        ├─ stand / walk / animation / fallen / off
           └───────────────────────┘        ├─ 走路：WalkController + ONNX AI（policy.py）
                                            ├─ 動作：關鍵影格動畫（animation.py + animations/*.json）
                                            └─ 安全：關節角度限制、限速、跌倒偵測、開機緩啟動
                                                      │
                                ┌─────────────────────┼─────────────────────┐
                           MockBackend          MujocoBackend          HardwareBackend
                          （純軟體假身體）       （物理模擬）       （feetech.py + BNO055 + 腳底開關）
```

| 檔案 | 做什麼 |
|---|---|
| `duck_robot/feetech.py` | **從零寫的** STS3215 通訊協定（封包、checksum、同步讀寫），適合拿來學 |
| `duck_robot/policy.py` | 把感測資料組成 101 維觀測 → AI → 14 個馬達角度 |
| `duck_robot/controller.py` | 主迴圈、狀態機、安全保護 |
| `duck_robot/animation.py` | 讀 JSON 動畫、平滑內插 |
| `duck_robot/server.py` | HTTP API + 手機遙控網頁 |
| `duck_robot/backends/` | mock / sim / hw 三種身體 |
| `duck_robot/cli.py` | `scan`、`set-id`、`check-motors`、`calibrate`、`run` 等指令 |

---

## 三、還沒買零件？先在電腦上玩

```bash
cd robot
pip install -e ".[sim,dev]"

# 1) 純軟體假身體 + 手機遙控網頁
python -m duck_robot run --backend mock --http 127.0.0.1:8000
#    打開 http://127.0.0.1:8000/ 按按鈕

# 2) MuJoCo 物理模擬 + 真正的 AI 走路
git clone https://github.com/apirrone/Open_Duck_Playground
git clone -b v2 https://github.com/apirrone/Open_Duck_Mini   # 裡面有 BEST_WALK_ONNX_2.onnx
python -m duck_robot run --backend sim --viewer \
  --sim-xml Open_Duck_Playground/playground/open_duck_mini_v2/xmls/scene_flat_terrain.xml \
  --policy Open_Duck_Mini/BEST_WALK_ONNX_2.onnx \
  --http 127.0.0.1:8000
```

用 curl 也可以控制：

```bash
curl -X POST localhost:8000/command -d '{"action":"walk","vx":0.15,"duration":3}'
curl -X POST localhost:8000/command -d '{"action":"play","name":"dance"}'
curl localhost:8000/status
```

### 指令一覽

| 指令 | 範例 |
|---|---|
| 走路（vx 前後 ±0.15 m/s、vy 左右 ±0.2、wz 轉向 ±1 rad/s） | `{"action":"walk","vx":0.1,"wz":0.3,"duration":2}` |
| 停下 | `{"action":"stop"}` |
| 轉頭 | `{"action":"head","head_yaw":0.5,"neck_pitch":0.2}` |
| 播動畫 | `{"action":"play","name":"nod"}` |
| 站好（跌倒後也用這個） | `{"action":"stand"}` |
| 放鬆馬達 | `{"action":"torque","enabled":false}` |

內建動畫：`nod` 點頭、`shake` 搖頭、`look_around` 東張西望、`crouch` 蹲下、`happy` 開心、`dance` 跳舞。
**全部都在 MuJoCo 裡測過不會跌倒**（`tests/test_sim_walk.py`）。

---

## 四、組裝完成後的步驟（在 Raspberry Pi 上）

```bash
# 0) 系統：Raspberry Pi OS Lite 64-bit，開 SSH、用 raspi-config 開 I2C
sudo apt install -y git python3-pip python3-venv
git clone <這個 repo> && cd <repo>/robot
python3 -m venv ~/duck && source ~/duck/bin/activate
pip install -e ".[hw,gamepad]"

# 1) 設定馬達 ID：新馬達出廠都是 ID 1，「一次只接一顆」
python -m duck_robot set-id --new 10      # 接右髖 yaw 那顆，依上面的表格逐顆設定
python -m duck_robot scan                 # 全部接上後確認 14 個 ID 都在

# 2) 建立設定檔並檢查
cp config/duck_config.example.json ~/duck_config.json
python -m duck_robot check-motors --config ~/duck_config.json

# 3) 校正：程式會逐一放鬆每個關節，請你把它轉到組裝指南上的零點刻度
#    （零點 = CAD 模型裡所有關節角度為 0 的姿勢，腿接近伸直、頭朝正前方）
python -m duck_robot calibrate --config ~/duck_config.json
python -m duck_robot calibrate --config ~/duck_config.json --joint left_knee   # 只重做某一個

# 4) 先「吊著」測試（腳不要碰地！）
python -m duck_robot run --backend hw --config ~/duck_config.json --http 0.0.0.0:8000 --token 你的密碼

# 5) 放到地上、加上 AI 走路與手把
python -m duck_robot run --backend hw --config ~/duck_config.json \
  --policy ~/BEST_WALK_ONNX_2.onnx --gamepad --http 0.0.0.0:8000 --token 你的密碼
```

⚠️ **安全須知**
- 第一次開機一定要把鴨子吊起來或拿在手上，確認每個關節方向正確再放地上。
- 校正偏移超過 0.3 rad 會出現警告，通常是舵盤裝錯一格，請拆下來重裝。
- 傾斜超過 55° 會判定跌倒，馬達自動變軟保護齒輪；送 `stand` 才會重新出力。
- `--http 0.0.0.0` 對外開放時**一定要加 `--token`**。

---

## 五、自己寫動作（不用 AI）

在任何資料夾新增 JSON，例如 `my_anims/wiggle.json`：

```json
{
  "name": "wiggle",
  "description": "扭扭頭",
  "keyframes": [
    {"t": 0.0, "pose": {}},
    {"t": 0.5, "pose": {"head_roll": 0.3, "crouch": 0.1}},
    {"t": 1.0, "pose": {"head_roll": -0.3, "crouch": 0.1}},
    {"t": 1.5, "pose": {}}
  ]
}
```

- `pose` 是相對站姿的偏移（弧度），沒寫到的關節就保持站姿。
- `crouch`（0～0.5）會自動換算成髖、膝、踝，讓腳掌保持水平。
- 第一格和最後一格建議都是 `{}`，才能和其他動作接得順。
- 啟動時加 `--anim-dir my_anims`，**先在 sim 裡試**：太快的動作會摔倒（內建 dance 每拍 0.4 秒會倒、0.8 秒才穩）。

---

## 六、用 LINE 控制鴨子

這個 repo 本來就是 LINE GPT 機器人，已經加好 `app/handlers/duck.js`。
在 LINE bot 的環境變數加上：

```
DUCK_API_URL=https://你的鴨子網址      # 鴨子在家裡網路時，可用 Cloudflare Tunnel 或 ngrok 對外
DUCK_API_TOKEN=你的密碼                # 跟 --token 一樣
```

然後在 LINE 輸入：`鴨子 前進 5 秒`、`鴨子 左轉`、`鴨子 跳舞`、`鴨子 狀態`、`鴨子 停`……

---

## 七、學習路線建議

1. **Python 基礎**（變數、迴圈、函式、class）→ 讀 `animation.py`，自己寫幾個動畫。
2. **通訊協定**：讀 `feetech.py` 和 `tests/test_feetech.py`，搭配 Feetech STS3215 記憶體表，理解封包怎麼組。
3. **控制迴圈**：讀 `controller.py`，理解 50 Hz、狀態機、為什麼要限速和緩啟動。
4. **強化學習**：讀 `policy.py` 理解 AI 的輸入輸出，再到
   [Open_Duck_Playground](https://github.com/apirrone/Open_Duck_Playground)（MuJoCo Playground）
   或 [microduck_rl](https://github.com/pollen-robotics/microduck_rl)（mjlab）學怎麼訓練自己的步態，需要 NVIDIA GPU。
5. 社群：Open Duck Mini 的 Discord 有很多人分享組裝經驗。

---

## 測試

```bash
pip install -e ".[sim,dev]" onnx
python -m pytest                     # 單元測試（不需要硬體）

# 加上 MuJoCo 實際走路 / 動畫平衡測試
DUCK_SIM_XML=Open_Duck_Playground/playground/open_duck_mini_v2/xmls/scene_flat_terrain.xml \
DUCK_POLICY=Open_Duck_Mini/BEST_WALK_ONNX_2.onnx python -m pytest
```

## 致謝與授權

- 硬體設計、步行模型、模擬模型：[Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini)、
  [Open Duck Playground](https://github.com/apirrone/Open_Duck_Playground)（Apache-2.0），作者 Antoine Pirrone 與社群。
- 本資料夾的程式為獨立撰寫，觀測向量格式依照 Open Duck Mini Runtime 以相容其模型。
