from pathlib import Path
import hashlib
T=Path('/tmp/iter63-r08-packaging-j8KrE0I2')
rows=(T/'test-manifest.txt').read_text().splitlines()
for row in rows:
 h,rest=row.split(' ',1); src,dst=rest.split(' -> ')
 assert hashlib.sha256(Path(src).read_bytes()).hexdigest()==h
 assert hashlib.sha256(Path(dst).read_bytes()).hexdigest()==h
print('PUBLIC_TEST_SOURCE_AND_MIRROR_SHA_MATCH',len(rows))
