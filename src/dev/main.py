from machine import UART, Pin
import time
import ujson
import math

# =====================
# 設定・定数（ご提示の値を初期値として反映）
# =====================
N             = 30.0   # 総パルス倍率 (1.0 = 1000 steps)
K_WEIGHT      = 0.5    # 黒(K)の着色力補正
GAMMA_K       = 1.5    # 閾値を超えた後のKの立ち上がりカーブ
GAMMA_COLOR   = 2.0    # カラーの立ち上がりカーブ（大きいほど薄い色の時の水が増える）
KW_THRESHOLD  = 30     # Kを使い始める境界線（小さいほど早く黒が出始める）
STEP_DELAY_US = 700    # モーターのパルス間隔

# --- ニュアンス維持のための追加設定 ---
RETAIN_CMY_RATIO = 0.4 # CMYの共通成分をどれだけ「残す」か (0.0〜1.0)
                       # 0.0=完全にK置換, 1.0=Kを使わずCMYのみでグレーを作る

DIR_NORMAL   = 1      
DIR_REVERSE  = 0      

# ピンアサイン
STEP_PINS = (16, 17, 18, 19, 20) # C, M, Y, K, W
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
# 調色ロジック (CMY共存 + ガンマ補正版)
# =====================

def convert_to_watercolor_steps(c, m, y, k):
    # 1. グレー成分の抽出
    gray_component = min(c, m, y)
    
    # 2. CMYをどれだけ残すかの計算 (UCR調整)
    # 共通成分のうち、一部をKに置き換え、一部をCMYとして残す
    replace_to_k = gray_component * (1.0 - RETAIN_CMY_RATIO)
    
    # 置き換えられなかった分がCMYとして残り、3色混合の深みを作る
    c_raw = c - replace_to_k
    m_raw = m - replace_to_k
    y_raw = y - replace_to_k
    k_combined = k + replace_to_k

    # 3. カラー成分(C,M,Y)へのガンマ補正
    # 薄い色の時に水の比率を稼ぐ
    c_f = math.pow(c_raw / 100.0, GAMMA_COLOR) * 100
    m_f = math.pow(m_raw / 100.0, GAMMA_COLOR) * 100
    y_f = math.pow(y_raw / 100.0, GAMMA_COLOR) * 100

    # 4. K(黒)とW(水)の比率計算
    k_out = 0
    w_out = 0

    if k_combined <= KW_THRESHOLD:
        k_out = 0
        w_out = 100 
    else:
        range_width = 100 - KW_THRESHOLD
        k_input_norm = (k_combined - KW_THRESHOLD) / range_width
        k_ratio = math.pow(k_input_norm, GAMMA_K)
        
        k_out = k_ratio * 100 * K_WEIGHT
        w_out = (1.0 - k_ratio) * 100

    # 5. 比率の合成と正規化
    raw_ratios = [c_f, m_f, y_f, k_out, w_out]
    total_raw = sum(raw_ratios)
    
    if total_raw == 0:
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
        d = DIR_REVERSE if pumps.get("reverse") else DIR_NORMAL
        for pin in dir_pins: pin(d)
        for i, k in enumerate(keys): en_pins[i](0 if pumps.get(k) else 1)
        interrupted = True
        
    elif cmd == "color":
        mode = "auto"
        raw = msg.get("cmyk", {"c":0,"m":0,"y":0,"k":0})
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
    
    for i in range(5):
        if step_list[i] > 0:
            en_pins[i](0)
            dir_pins[i](DIR_NORMAL)
    
    max_s = max(step_list)
    for s in range(max_s):
        if s % 10 == 0 and check_uart():
            break 
        
        for i in range(5):
            if s < step_list[i]: step_pins[i](1)
        time.sleep_us(STEP_DELAY_US)
        for i in range(5): step_pins[i](0)
        time.sleep_us(STEP_DELAY_US)
    
    for p in en_pins: p(1)

# =====================
# メインループ
# =====================
for p in en_pins: p(1)
print("--- Watercolor Driver (Nuance-Keep Mode) ---")
print("Settings: N={}, G_COLOR={}, G_K={}, THR={}, RETAIN_CMY={}".format(N, GAMMA_COLOR, GAMMA_K, KW_THRESHOLD, RETAIN_CMY_RATIO))

while True:
    check_uart()
    
    if mode == "manual":
        any_on = False
        for i, k in enumerate(keys):
            if pumps.get(k):
                step_pins[i](1)
                any_on = True
        if any_on:
            time.sleep_us(STEP_DELAY_US)
            for p in step_pins: p(0)
            time.sleep_us(STEP_DELAY_US)
            
    elif mode == "auto":
        if sum(auto_target_steps) > 0:
            print("Auto Mixing Steps (C,M,Y,K,W):", auto_target_steps)
            drive_auto_steps(auto_target_steps)
            auto_target_steps = [0, 0, 0, 0, 0]
            if mode == "auto":
                mode = "manual"