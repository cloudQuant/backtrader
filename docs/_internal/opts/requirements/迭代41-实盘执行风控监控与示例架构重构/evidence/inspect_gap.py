from pathlib import Path
b=Path('README.md').read_bytes()
i=b.find(b'### G1 R10-r1 inert deadline/shutdown evidence')
j=b.find(b'**BtApiStore AccountActorPort',i)
print(repr(b[j-100:j+50]))
