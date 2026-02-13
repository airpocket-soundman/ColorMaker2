from machine import UART
from machine import Pin
import time
import utime


uart0 = UART(0)

enable = Pin(2,Pin.OUT)
direction = Pin(3,Pin.OUT)

stepW = Pin(9,Pin.OUT)
stepC = Pin(5,Pin.OUT)
stepM = Pin(6,Pin.OUT)
stepY = Pin(7,Pin.OUT)
stepK = Pin(8,Pin.OUT)


enable(1)

stepC(0)
stepM(0)
stepY(0)
stepK(0)
stepW(0)
   
    
class motor():
    def __init__(self):

        self.C = 0
        self.M = 0
        self.Y = 0
        self.K = 0
        self.W = 0
        self.Cx = 1
        self.Mx = 1
        self.Yx = 1
        self.Kx = 1
        self.Wx = 1
        self.stepX = 1
        self.stepNumC = 0
        self.stepNumM = 0
        self.stepNumY = 0
        self.stepNumK = 0
        self.stepNumW = 0
        self.maxStepNum = 0
        self.targetSteps = 2000
        print("motor initialized")

    def calcSteps(self):
        print("drive!!")
        self.stepNumC = self.C * self.Cx
        self.stepNumM = self.M * self.Mx
        self.stepNumY = self.Y * self.Yx
        self.stepNumK = self.K * self.Kx
        self.stepNumW = (100 - self.K) * self.Wx * self.stepX
        self.maxStepNum = max(self.stepNumC, self.stepNumM, self.stepNumY, self.stepNumK)
        stepNumAdd = self.stepNumC + self.stepNumM + self.stepNumY + self.stepNumK
        if stepNumAdd > 0:
            self.stepX = round(self.targetSteps/stepNumAdd)
            self.stepNumC = self.stepNumC * self.stepX
            self.stepNumM = self.stepNumM * self.stepX
            self.stepNumY = self.stepNumY * self.stepX
            self.stepNumK = self.stepNumK * self.stepX
            self.stepNumW = self.stepNumW * self.stepX
            stepNumAdd = self.stepNumC + self.stepNumM + self.stepNumY + self.stepNumK
            self.maxStepNum = self.maxStepNum * self.stepX
                
        print("maxStepNum = " + str(self.maxStepNum))
        print("stepNumAdd = " + str(stepNumAdd))
        print("stepX = " + str(self.stepX))
        print("stepNumC = " + str(self.stepNumC))
        print("stepNumM = " + str(self.stepNumM))
        print("stepNumY = " + str(self.stepNumY))
        print("stepNumK = " + str(self.stepNumK))
        print("stepNumW = " + str(self.stepNumW))
        
        motor.drive()
        
    def drive(self):

        direc = 0
        step_delay = 2000   # ここは自由に調整（例：2000〜4000）

        direction(direc)
        enable(0)           # ★ 回転中は常に ENABLE ON

        print("[DRIVE] start, delay_us =", step_delay)

        for i in range(self.maxStepNum):

            # ===== STEP ON =====
            if i < self.stepNumC:
                stepC(1)
            if i < self.stepNumM:
                stepM(1)
            if i < self.stepNumY:
                stepY(1)
            if i < self.stepNumK:
                stepK(1)

            time.sleep_us(5)   # STEPパルス幅（A4988は1us以上でOK）

            # ===== STEP OFF =====
            stepC(0)
            stepM(0)
            stepY(0)
            stepK(0)

            time.sleep_us(step_delay)

        enable(1)   # ★ 完全停止してから disable
        print("[DRIVE] end")


        enable(1)
        print(i)
        print("end")
        print("maxStepNum = " + str(self.maxStepNum))
#        print("stepNumAdd = " + str(stepNumAdd))
        print("stepX = " + str(self.stepX))
        print("stepNumC = " + str(self.stepNumC))
        print("stepNumM = " + str(self.stepNumM))
        print("stepNumY = " + str(self.stepNumY))
        print("stepNumK = " + str(self.stepNumK))
        print("stepNumW = " + str(self.stepNumW))
        
motor = motor()

while True:
#    go = input("any key to start")
    mes = ""
    c = 0
    c = uart0.any()
    while c > 0:
#        print("c = " + str(c))
        time.sleep_ms(50)
        l = uart0.readline()
        m = ""
        if l != None:
            print("=======================")
            print("catch comm")
            print(l)
            try:
#                m = l.decode("utf-8")
                m = str(l)
#                print(type(m))
                m = m[2:3]
#                print("l = " + m)
#                print(str(m))

            except:
                print("cant decode")
            
            if m == "s":
                print("Start")
                try:
                    motor.C = uart0.readline()
                    print(motor.C)
#                    motor.C = motor.C.decode("utf-8")
                    motor.C = int(motor.C)
                    print("C = " + str(motor.C))
                except:
                    print("cant read C")
                    break
                
                time.sleep(0.1)
                
                try:
                    motor.M = uart0.readline()
                    print(motor.M)
#                    motor.M = motor.M.decode("utf-8")
                    motor.M = int(motor.M)
                    print("M = " + str(motor.M))
                except:
                    print("cant read M")
                    break
                    
                time.sleep(0.1)
                
                try:
                    motor.Y = uart0.readline()
                    print(motor.Y)
#                    motor.Y = motor.C.decode("utf-8")
                    motor.Y = int(motor.Y)
                    print("Y = " + str(motor.Y))
                except:
                    print("cant read Y")
                    break
                    
                time.sleep(0.1)
                
                try:
                    motor.K = uart0.readline()
                    print(motor.K)
#                    motor.K = motor.K.decode("utf-8")
                    motor.K = int(motor.K)
                    print("K = " + str(motor.K))
                except:
                    print("cant read K")
                    break
                motor.calcSteps()
                
            else:
                print("not s")
        c = 0
