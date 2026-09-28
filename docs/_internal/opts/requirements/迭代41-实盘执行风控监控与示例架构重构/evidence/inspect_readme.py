from pathlib import Path
p=Path('README.md')
b=p.read_bytes()
print('bytes',len(b),'CRLF',b.count(b'\r\n'),'LF',b.count(b'\n'),'BOM',b.startswith(b'\xef\xbb\xbf'))
needle='### G1 R10-r1 inert deadline/shutdown evidence (2026-09-27)'.encode()
i=b.find(needle)
print('heading_idx',i)
print(repr(b[i:i+1100]))
