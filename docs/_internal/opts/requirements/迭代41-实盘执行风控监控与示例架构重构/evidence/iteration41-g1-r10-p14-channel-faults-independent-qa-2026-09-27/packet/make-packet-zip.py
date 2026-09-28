import pathlib, sys, zipfile
root=pathlib.Path(sys.argv[1]); out=root/'independent-qa.raw.zip'
with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.name not in {'independent-qa.raw.zip','packet-manifest.json'}:
            z.write(p,p.relative_to(root).as_posix())