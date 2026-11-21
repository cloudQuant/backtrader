import json,sys
from pathlib import Path
rows=json.loads((Path(__file__).parent/'instrument.json').read_text(encoding='utf-8'))
x=next(row for row in rows if row['version']==sys.argv[1])
assert x['missing_attr']=={'_once_called':0,'_resolved_secondary_clock':0},x['missing_attr']
print('PASS_MISSING_ATTRIBUTE_EXCEPTION_COUNT_ZERO')
