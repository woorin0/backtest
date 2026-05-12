import urllib.request
import urllib.parse
from html.parser import HTMLParser
import re

url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote("pine script ta.rma initial seed sma")
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())
p = P()
p.feed(html)
print(" ".join(p.text))
