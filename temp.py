import re

app_path = r'd:\Anti\파이썬 백테스트\파이썬 백테스트\app.py'
txt_path = r'd:\Anti\파이썬 백테스트\백테스트 사용\백테스트 전략 코드(backtrader).txt'

with open(app_path, 'r', encoding='utf-8') as f:
    content = f.read()

with open(txt_path, 'r', encoding='utf-8') as f:
    new_code = f.read()

pattern = re.compile(r'(default_code = \"\"\")(.*?)(^    else:)', re.MULTILINE | re.DOTALL)

def replace_func(match):
    return f'{match.group(1)}\n{new_code}\n\"\"\"\n{match.group(3)}'

new_content = pattern.sub(replace_func, content)

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(new_content)
print("Inject success")
