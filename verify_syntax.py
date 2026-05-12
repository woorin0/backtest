import ast
try:
    with open("strategies/vectorbt.txt", "r") as f:
        ast.parse(f.read())
    print("Syntax OK")
except Exception as e:
    print(f"Syntax error: {e}")
