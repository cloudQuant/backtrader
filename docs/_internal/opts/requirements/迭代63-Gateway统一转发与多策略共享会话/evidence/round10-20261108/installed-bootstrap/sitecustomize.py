import os
from origin_guard import install
install('sitecustomize-subprocess')
if os.environ.get('R10_FAKE_NATIVE')=='1':
 from fake_native import install as fake
 fake()
