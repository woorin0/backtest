with open("core/data_fetcher.py", "r") as f:
    content = f.read()

search_str = """        # 🚨 [Bugfix] 연속 빈 응답 허용치를 패딩 기간 + 여유분(최대 10초 스캔 분량, 약 50번 점프)으로 동적 계산하여 조기 종료 방지
        max_empty_jumps = max(3, int(padding_candles / limit) + 50)"""

replace_str = """        # 🚨 [Bugfix] 연속 빈 응답 허용치를 패딩 기간 + 여유분(최대 10초 스캔 분량, 약 50번 점프)으로 동적 계산하여 조기 종료 방지
        safe_limit = max(limit, 1)
        max_empty_jumps = max(3, int(padding_candles / safe_limit) + 50)"""

if search_str in content:
    content = content.replace(search_str, replace_str)
    with open("core/data_fetcher.py", "w") as f:
        f.write(content)
    print("Patched successfully.")
else:
    print("Search string not found.")
