import os
paths = [
    "D:/Antigravity/백테스트 사용/백테스트 전략 코드(vectorbt).txt",
    "D:/Antigravity/백테스트 사용/백테스트 전략 코드(backtrader).txt",
    r"D:\Antigravity\백테스트 사용\백테스트 전략 코드(vectorbt).txt",
    r"D:\Antigravity\백테스트 사용\백테스트 전략 코드(backtrader).txt"
]

for p in paths:
    print(f"Path: {p} -> Exists: {os.path.exists(p)}")
