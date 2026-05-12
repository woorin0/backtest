import re

with open("strategies/vectorbt.txt", "r") as f:
    content = f.read()

# Replace pine_min logic
new_pine_min = """    def pine_min(a, b):
        if np.isnan(a): return b
        if np.isnan(b): return a
        return a if a < b else b"""

content = re.sub(
    r'    def pine_min\(a, b\):\n        if np\.isnan\(a\) or np\.isnan\(b\): return np\.nan\n        return a if a < b else b',
    new_pine_min,
    content
)

# Replace pine_max logic
new_pine_max = """    def pine_max(a, b):
        if np.isnan(a): return b
        if np.isnan(b): return a
        return a if a > b else b"""

content = re.sub(
    r'    def pine_max\(a, b\):\n        if np\.isnan\(a\) or np\.isnan\(b\): return np\.nan\n        return a if a > b else b',
    new_pine_max,
    content
)

# Also fix the np.maximum used outside of Numba:
# wait, what if I should fix `np.maximum` in Python level too?
# `hl_p = np.maximum(hott_s, bb_u)`
# The comment says: `# math.max()는 하나라도 na이면 na를 반환해야 하므로 np.fmax가 아닌 np.maximum 사용`
# Wait, this comment explicitly says math.max MUST propagate na!
# If the reviewer says "math.min and math.max ignore na values", then the comment `# math.max()는 하나라도 na이면 na를 반환해야 하므로 np.fmax가 아닌 np.maximum 사용` was WRONG!
# And I should change `np.maximum` to `np.fmax`.

content = content.replace("np.maximum", "np.fmax")
# also fix the comment so it doesn't contradict:
content = content.replace("# math.max()는 하나라도 na이면 na를 반환해야 하므로 np.fmax가 아닌 np.maximum 사용", "# Pine Script math.max() ignores na, so we use np.fmax")

with open("strategies/vectorbt.txt", "w") as f:
    f.write(content)
