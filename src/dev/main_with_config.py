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
STEP_DELAY_US = 1200    # 初期パルス間隔

RETAIN_CMY_RATIO = 0.4

DIR_NORMAL   = 1
DIR_REVERSE  = 0

# ピンアサイン
STEP_PINS = (16, 17, 18, 19, 20)  # C, M, Y, K, W
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

auto_target_steps = [0, 0, 0, 0, 0]
interrupted = False

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
    global mode, pumps, auto_target_steps, interrupted
    global N, K_WEIGHT, GAMMA_K, GAMMA_COLOR, KW_THRESHOLD, TOTAL_STEPS, STEP_DELAY_US

    print("Received JSON:", ujson.dumps(msg))
    cmd = msg.get("cmd", "")

    if cmd == "pump":
        mode = "manual"
        pumps.update(msg.get("pumps", {}))
        d = DIR_REVERSE if pumps.get("reverse") else DIR_NORMAL
        for pin in dir_pins: pin(d)
        interrupted = True

    elif cmd == "color":
        mode = "auto"
        raw = msg.get("cmyk", {"c": 0, "m": 0, "y": 0, "k": 0})
        auto_target_steps = convert_to_watercolor_steps(raw["c"], raw["m"], raw["y"], raw["k"])
        interrupted = True

    elif cmd == "config":
        cfg = msg.get("config", {})
        
        # 各項目が存在する場合のみ更新。存在しない場合は現在の値を維持。
        if "N" in cfg:
            N = float(cfg["N"]) * 10.0
            TOTAL_STEPS = int(N * 1000)
        
        if "GAMMA_COLOR" in cfg: 
            GAMMA_COLOR = float(cfg["GAMMA_COLOR"]) / 10.0
            
        if "GAMMA_K" in cfg: 
            GAMMA_K = float(cfg["GAMMA_K"]) / 10.0
            
        if "K_WEIGHT" in cfg: 
            K_WEIGHT = float(cfg["K_WEIGHT"]) / 10.0
            
        if "KW_THRESHOLD" in cfg: 
            KW_THRESHOLD = float(cfg["KW_THRESHOLD"]) / 10.0
        
        # STEP_DELAY_USがある場合のみ100倍して適用
        if "STEP_DELAY_US" in cfg:
            STEP_DELAY_US = int(float(cfg["STEP_DELAY_US"]) * 100)

        print("[CONFIG UPDATED] N:", N, "DELAY:", STEP_DELAY_US)
        interrupted = True

# =====================
# UART受信・駆動
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

def drive_auto_steps(step_list):
    global interrupted
    interrupted = False

    for i in range(5):
        if step_list[i] > 0:
            en_pins[i](0)
            dir_pins[i](DIR_NORMAL)

    max_s = max(step_list)
    for s in range(max_s):
        if interrupted or (s % 10 == 0 and check_uart()): break
        
        for i in range(5):
            if s < step_list[i]: step_pins[i](1)
        time.sleep_us(5)
        for i in range(5): step_pins[i](0)
        time.sleep_us(STEP_DELAY_US)

    for p in en_pins: p(1)

# =====================
# メインループ
# =====================
for p in en_pins: p(1)
print("--- Watercolor Driver (Smart Config Mode) ---")

while True:
    check_uart()

    if mode == "manual":
        any_on = False
        for i, k in enumerate(keys):
            is_active = pumps.get(k, False)
            en_pins[i](0 if is_active else 1)
            if is_active:
                step_pins[i](1)
                any_on = True

        if any_on:
            time.sleep_us(5)
            for p in step_pins: p(0)
            time.sleep_us(STEP_DELAY_US)
        else:
            time.sleep_ms(10)

    elif mode == "auto":
        if sum(auto_target_steps) > 0:
            print("Auto Mixing Steps:", auto_target_steps)
            drive_auto_steps(auto_target_steps)
            auto_target_steps = [0, 0, 0, 0, 0]
            mode = "manual"