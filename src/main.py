from machine import UART, Pin
import time
import ujson
import math

# =====================
# 設定・初期値（起動時デフォルト）
# =====================
N             = 30.0    # 総パルス倍率 (N * 1000 = TOTAL_STEPS)
K_WEIGHT      = 0.5
GAMMA_K       = 1.5
GAMMA_COLOR   = 2.0
KW_THRESHOLD  = 30.0
STEP_DELAY_US = 1200    # パルス間隔（configで上書き可能）

RETAIN_CMY_RATIO = 0.4

DIR_NORMAL   = 1
DIR_REVERSE  = 0

# ピンアサイン (C, M, Y, K, W)
STEP_PINS = (16, 17, 18, 19, 20)
DIR_PINS  = (21, 22, 26, 27, 28)
EN_PINS   = (2,  3,  4,  5,  6)

# =====================
# 初期化
# =====================
step_pins = [Pin(p, Pin.OUT) for p in STEP_PINS]
dir_pins  = [Pin(p, Pin.OUT) for p in DIR_PINS]
en_pins   = [Pin(p, Pin.OUT) for p in EN_PINS]

TOTAL_STEPS = int(N * 1000)

keys = ["c", "m", "y", "k", "w"]
mode = "manual"
pumps = {k: False for k in keys}
pumps["reverse"] = False

# 自動モード用カウンタ
auto_target_steps = [0, 0, 0, 0, 0]
auto_current_steps = [0, 0, 0, 0, 0]

uart = UART(0, baudrate=115200)
rx_buf = b""

# =====================
# 調色ロジック
# =====================
def convert_to_watercolor_steps(c, m, y, k):
    gray_component = min(c, m, y)
    replace_to_k = gray_component * (1.0 - RETAIN_CMY_RATIO)

    c_raw = max(0, c - replace_to_k)
    m_raw = max(0, m - replace_to_k)
    y_raw = max(0, y - replace_to_k)
    k_combined = min(100.0, k + replace_to_k)

    c_f = math.pow(c_raw / 100.0, GAMMA_COLOR) * 100.0
    m_f = math.pow(m_raw / 100.0, GAMMA_COLOR) * 100.0
    y_f = math.pow(y_raw / 100.0, GAMMA_COLOR) * 100.0

    if k_combined <= KW_THRESHOLD:
        k_out, w_out = 0.0, 100.0
    else:
        span = 100.0 - KW_THRESHOLD
        norm = (k_combined - KW_THRESHOLD) / span
        k_ratio = math.pow(norm, GAMMA_K)
        k_out = k_ratio * 100.0 * K_WEIGHT
        w_out = (1.0 - k_ratio) * 100.0

    raw = [c_f, m_f, y_f, k_out, w_out]
    total = sum(raw)
    if total <= 0: return [0, 0, 0, 0, 0]
    return [int((v / total) * TOTAL_STEPS) for v in raw]

# =====================
# JSONコマンド処理
# =====================
def handle_json(msg):
    global mode, pumps, auto_target_steps, auto_current_steps
    global N, K_WEIGHT, GAMMA_K, GAMMA_COLOR, KW_THRESHOLD, TOTAL_STEPS, STEP_DELAY_US

    print("Received JSON:", ujson.dumps(msg))
    cmd = msg.get("cmd", "")

    if cmd == "pump":
        mode = "manual"
        pumps.update(msg.get("pumps", {}))
        d = DIR_REVERSE if pumps.get("reverse") else DIR_NORMAL
        for pin in dir_pins: pin(d)
        
    elif cmd == "color":
        mode = "auto"
        raw = msg.get("cmyk", {"c": 0, "m": 0, "y": 0, "k": 0})
        auto_target_steps = convert_to_watercolor_steps(raw["c"], raw["m"], raw["y"], raw["k"])
        auto_current_steps = [0, 0, 0, 0, 0] # リセット
        for pin in dir_pins: pin(DIR_NORMAL) # 自動時は常に正転
        print("Auto Target Steps:", auto_target_steps)

    elif cmd == "config":
        cfg = msg.get("config", {})
        if "N" in cfg:
            N = float(cfg["N"]) * 10.0
            TOTAL_STEPS = int(N * 1000)
        if "GAMMA_COLOR" in cfg: GAMMA_COLOR = float(cfg["GAMMA_COLOR"]) / 10.0
        if "GAMMA_K" in cfg: GAMMA_K = float(cfg["GAMMA_K"]) / 10.0
        if "K_WEIGHT" in cfg: K_WEIGHT = float(cfg["K_WEIGHT"]) / 10.0
        if "KW_THRESHOLD" in cfg: KW_THRESHOLD = float(cfg["KW_THRESHOLD"]) / 10.0
        if "STEP_DELAY_US" in cfg:
            STEP_DELAY_US = int(float(cfg["STEP_DELAY_US"]) * 100)
        print("[CONFIG UPDATED] N:", N, "DELAY:", STEP_DELAY_US)

# =====================
# UART受信
# =====================
def check_uart():
    global rx_buf
    if uart.any():
        try:
            raw = uart.read()
            if raw:
                rx_buf += raw
                if b"\n" in rx_buf:
                    line, rx_buf = rx_buf.split(b"\n", 1)
                    s = line.decode().strip()
                    if s:
                        handle_json(ujson.loads(s))
                        return True
        except: pass
    return False

# =====================
# メインループ (High Stability Integration)
# =====================
for p in en_pins: p(1)
print("--- Watercolor Driver (Unified Loop Mode) ---")

while True:
    check_uart()

    any_on = False
    active_now = [False] * 5

    # 現在のモードに基づき、どのポンプを1ステップ動かすか判定
    if mode == "manual":
        for i, k in enumerate(keys):
            if pumps.get(k, False):
                active_now[i] = True
                any_on = True
    
    elif mode == "auto":
        for i in range(5):
            if auto_current_steps[i] < auto_target_steps[i]:
                active_now[i] = True
                any_on = True

    # 共通パルス駆動
    if any_on:
        # ステップ信号をHIGHにする
        for i in range(5):
            en_pins[i](0 if active_now[i] else 1) # 動かすピンだけ有効化
            if active_now[i]:
                step_pins[i](1)
        
        time.sleep_us(5) # パルス幅保持
        
        # ステップ信号をLOWにする
        for i in range(5):
            step_pins[i](0)
            if mode == "auto" and active_now[i]:
                auto_current_steps[i] += 1
        
        # 次のステップまでの待機（ここが安定の要）
        time.sleep_us(STEP_DELAY_US)
        
    else:
        # 動くべきポンプがない場合
        if mode == "auto":
            # すべての目標ステップが完了
            print("Auto Sequence Done.")
            mode = "manual"
            # すべてのポンプ状態をオフにリセット
            for k in keys: pumps[k] = False
        
        # 待機中は発熱防止のため全Disable
        for p in en_pins: p(1)
        time.sleep_ms(10) # 通信待ち受けのための微小待機