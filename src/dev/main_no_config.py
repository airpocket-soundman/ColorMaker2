from machine import UART, Pin
import time
import ujson
import math

# =====================
# 設定・定数
# =====================
N             = 30.0   # 総パルス倍率 (1.0 = 1000 steps)
K_WEIGHT      = 0.5    # 黒(K)の着色力補正
GAMMA_K       = 1.5    # 閾値を超えた後のKの立ち上がりカーブ
GAMMA_COLOR   = 2.0    # カラーの立ち上がりカーブ
KW_THRESHOLD  = 30     # Kを使い始める境界線
STEP_DELAY_US = 1100    # モーターのパルス間隔

RETAIN_CMY_RATIO = 0.4 # CMYの共通成分をどれだけ「残す」か

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
auto_target_steps = [0, 0, 0, 0, 0]
interrupted = False
uart = UART(0, baudrate=115200)
rx_buf = b""

# =====================
# 調色ロジック
# =====================
def convert_to_watercolor_steps(c, m, y, k):
    # 1. グレー成分の抽出
    gray_component = min(c, m, y)
    
    # 2. UCR調整
    replace_to_k = gray_component * (1.0 - RETAIN_CMY_RATIO)
    
    c_raw = max(0, c - replace_to_k)
    m_raw = max(0, m - replace_to_k)
    y_raw = max(0, y - replace_to_k)
    k_combined = k + replace_to_k

    # 3. ガンマ補正
    c_f = math.pow(c_raw / 100.0, GAMMA_COLOR) * 100
    m_f = math.pow(m_raw / 100.0, GAMMA_COLOR) * 100
    y_f = math.pow(y_raw / 100.0, GAMMA_COLOR) * 100

    # 4. K/W比率
    k_out = 0.0
    w_out = 0.0
    if k_combined <= KW_THRESHOLD:
        k_out = 0.0
        w_out = 100.0
    else:
        range_width = 100.0 - KW_THRESHOLD
        k_input_norm = (k_combined - KW_THRESHOLD) / range_width
        k_ratio = math.pow(k_input_norm, GAMMA_K)
        k_out = k_ratio * 100.0 * K_WEIGHT
        w_out = (1.0 - k_ratio) * 100.0

    # 5. 正規化
    raw_ratios = [c_f, m_f, y_f, k_out, w_out]
    total_raw = sum(raw_ratios)
    
    if total_raw <= 0:
        return [0, 0, 0, 0, 0]

    return [int((val / total_raw) * TOTAL_STEPS) for val in raw_ratios]

# =====================
# 制御・通信
# =====================
def handle_json(msg):
    global mode, pumps, auto_target_steps, interrupted
    
    print("Received JSON:", ujson.dumps(msg))
    cmd = msg.get("cmd", "")
    
    if cmd == "pump":
        mode = "manual"
        pumps.update(msg.get("pumps", {}))
        # 方向転換の反映
        d = DIR_REVERSE if pumps.get("reverse") else DIR_NORMAL
        for pin in dir_pins:
            pin(d)
        interrupted = True
        
    elif cmd == "color":
        mode = "auto"
        raw = msg.get("cmyk", {"c":0, "m":0, "y":0, "k":0})
        auto_target_steps = convert_to_watercolor_steps(raw['c'], raw['m'], raw['y'], raw['k'])
        interrupted = True

def check_uart():
    global rx_buf
    if uart.any():
        try:
            raw = uart.read()
            if raw:
                rx_buf += raw
                if b"\n" in rx_buf:
                    line, rx_buf = rx_buf.split(b"\n", 1)
                    decoded_str = line.decode().strip()
                    if decoded_str:
                        handle_json(ujson.loads(decoded_str))
                        return True
        except Exception as e:
            print("UART Error:", e)
    return False

def drive_auto_steps(step_list):
    global interrupted
    interrupted = False
    
    # 使用するモーターを有効化
    for i in range(5):
        if step_list[i] > 0:
            en_pins[i](0)
            dir_pins[i](DIR_NORMAL)
    
    max_s = max(step_list)
    for s in range(max_s):
        # 10ステップごとにUARTを確認して割り込みチェック
        if s % 10 == 0 and check_uart():
            if interrupted: break 
        
        for i in range(5):
            if s < step_list[i]: 
                step_pins[i](1)
        time.sleep_us(5) # パルス幅確保
        for i in range(5): 
            step_pins[i](0)
        time.sleep_us(STEP_DELAY_US)
    
    # 終了後にすべてのモーターを無効化（発熱防止）
    for p in en_pins: 
        p(1)

# =====================
# メインループ
# =====================
# 初期状態はすべてDisable
for p in en_pins: p(1)

print("--- Watercolor Driver (Nuance-Keep Mode) ---")
print("Settings: N={}, G_COLOR={}, G_K={}, THR={}, RETAIN_CMY={}".format(N, GAMMA_COLOR, GAMMA_K, KW_THRESHOLD, RETAIN_CMY_RATIO))

while True:
    check_uart()
    
    if mode == "manual":
        any_on = False
        for i, k in enumerate(keys):
            is_active = pumps.get(k, False)
            # Enableピンの制御 (0=ON, 1=OFF)
            en_pins[i](0 if is_active else 1)
            
            if is_active:
                step_pins[i](1)
                any_on = True
                
        if any_on:
            time.sleep_us(5)
            for p in step_pins: 
                p(0)
            time.sleep_us(STEP_DELAY_US)
        else:
            # 何も動いていない時は少し待機してCPU負荷を下げる
            time.sleep_ms(10)
            
    elif mode == "auto":
        if sum(auto_target_steps) > 0:
            print("Auto Mixing Steps (C,M,Y,K,W):", auto_target_steps)
            drive_auto_steps(auto_target_steps)
        
        # 完了または中断後は手動モードへ戻る
        auto_target_steps = [0, 0, 0, 0, 0]
        mode = "manual"
        # ポンプ状態をリセット
        for k in keys: pumps[k] = False