from machine import Pin
import time
import sys
import select

# =====================
# Pin assign
# =====================
enable = Pin(2, Pin.OUT)
direction = Pin(3, Pin.OUT)
step = Pin(4, Pin.OUT)

ms1 = Pin(6, Pin.OUT)
ms2 = Pin(7, Pin.OUT)
ms3 = Pin(8, Pin.OUT)

# =====================
# Motor constants
# =====================
GEAR_STEPS = 2038        # 28BYJ-48 output shaft full steps
MICROSTEP_TABLE = {
    "full": 1,
    "half": 2,
    "quarter": 4,
    "eighth": 8,
    "sixteenth": 16,
}

# =====================
# Initial state
# =====================
enable(0)       # ※動かなければ 1 に変更
direction(0)
step(0)

ms1(0)
ms2(0)
ms3(0)

microstep_mode = "full"
step_delay_us = None
running = False
last_state = None

print("MPY: soft reboot")
print("microstep =", microstep_mode)

# =====================
# Helper display
# =====================
def show_commands(waiting=True):
    print("[COMMANDS]")
    print("  speed(us) : e.g. 2000, 1500, 800")
    print("  microstep : full / half / quarter / eighth / sixteenth")
    if waiting:
        print("  stop      : stop / s / 0")

def calc_rpm(delay_us, microstep):
    steps_per_sec = 1_000_000 / (delay_us * 2)
    rpm = (steps_per_sec * 60) / (GEAR_STEPS * microstep)
    return rpm

def show_state():
    global last_state
    state = "RUNNING" if running else "WAITING"

    if state != last_state:
        print("=========================")
        if state == "WAITING":
            print("[STATE] WAITING FOR COMMAND")
            show_commands(True)
        else:
            micro_div = MICROSTEP_TABLE[microstep_mode]
            rpm = calc_rpm(step_delay_us, micro_div)
            print("[STATE] RUNNING")
            print("  microstep :", microstep_mode, f"(x{micro_div})")
            print("  delay_us  :", step_delay_us)
            print("  RPM(out)  : {:.2f}".format(rpm))
            show_commands(False)
        print("=========================")
        last_state = state

# =====================
# Microstep control
# =====================
def set_microstep(mode):
    global microstep_mode

    if mode == "full":
        ms1(0); ms2(0); ms3(0)
    elif mode == "half":
        ms1(1); ms2(0); ms3(0)
    elif mode == "quarter":
        ms1(0); ms2(1); ms3(0)
    elif mode == "eighth":
        ms1(1); ms2(1); ms3(0)
    elif mode == "sixteenth":
        ms1(1); ms2(1); ms3(1)
    else:
        print("[WARN] Unknown microstep:", mode)
        return

    microstep_mode = mode
    print("[SET] microstep =", microstep_mode)

# =====================
# STEP pulse
# =====================
def step_once(delay_us):
    step(1)
    time.sleep_us(delay_us)
    step(0)
    time.sleep_us(delay_us)

# =====================
# Main loop
# =====================
poll = select.poll()
poll.register(sys.stdin, select.POLLIN)

show_state()

while True:

    if poll.poll(0):
        line = sys.stdin.readline().strip()

        # ★ 空行ガード（超重要）
        if not line:
            continue

        print("[RX]", line)

        if line in ("stop", "s", "0"):
            running = False
            enable(1)
            print("[STATE] STOPPED -> WAITING")
            show_state()
            continue

        if line.isdigit():
            step_delay_us = int(line)
            running = True
            enable(0)
            show_state()
            continue

        set_microstep(line.lower())


    if running and step_delay_us is not None:
        step_once(step_delay_us)
    else:
        time.sleep(0.01)


