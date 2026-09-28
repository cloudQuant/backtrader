from pathlib import Path
import zipfile, hashlib, struct, datetime, json
paths={
 'build_a':Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\build-a\wheelhouse\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),
 'build_b':Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\build-b\wheelhouse\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),
 'pinned':Path(r'D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),
}
member='bt_api_ctp/ctp/_ctp.cp311-win_amd64.pyd'
def parse(data):
    peoff=struct.unpack_from('<I',data,0x3c)[0]
    assert data[peoff:peoff+4]==b'PE\0\0'
    machine,nsec,tstamp,ptrsym,numsym,opsize,chars=struct.unpack_from('<HHIIIHH',data,peoff+4)
    opt=peoff+24
    magic=struct.unpack_from('<H',data,opt)[0]
    dd=opt+(112 if magic==0x20b else 96)
    debug_rva,debug_size=struct.unpack_from('<II',data,dd+6*8)
    sections=[]
    sh=opt+opsize
    for i in range(nsec):
        off=sh+i*40; rawname=data[off:off+8].split(b'\0')[0].decode('ascii','replace')
        vsize,va,rawsize,rawptr=struct.unpack_from('<IIII',data,off+8)
        sections.append((rawname,va,max(vsize,rawsize),rawptr,rawsize))
    def rvaoff(rva):
        for name,va,size,rawptr,rawsize in sections:
            if va<=rva<va+size: return rawptr+(rva-va)
        return None
    dbg_off=rvaoff(debug_rva) if debug_rva else None
    entries=[]
    if dbg_off:
      for i in range(debug_size//28):
        eoff=dbg_off+i*28
        characteristics,ts,maj,minor,typ,size,address,pointer=struct.unpack_from('<IIHHIIII',data,eoff)
        payload=data[pointer:pointer+size]
        entries.append({'entry_file_offset':hex(eoff),'timestamp_hex':hex(ts),'timestamp_utc':datetime.datetime.fromtimestamp(ts,datetime.timezone.utc).isoformat() if ts else None,'type':typ,'size':size,'addr':hex(address),'ptr':hex(pointer),'data_prefix':payload[:32].hex(),'data_ascii':payload[:100].decode('ascii','replace')})
    return {'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'pe_offset':hex(peoff),'machine':hex(machine),'coff_timestamp_hex':hex(tstamp),'coff_timestamp_utc':datetime.datetime.fromtimestamp(tstamp,datetime.timezone.utc).isoformat() if tstamp else None,'optional_magic':hex(magic),'debug_rva':hex(debug_rva),'debug_size':debug_size,'debug_file_offset':hex(dbg_off) if dbg_off else None,'sections':[{'name':n,'va':hex(va),'span':hex(size),'rawptr':hex(rawptr),'rawsize':hex(rawsize)} for n,va,size,rawptr,rawsize in sections],'debug_entries':entries}
blobs={}
for key,p in paths.items():
 with zipfile.ZipFile(p) as z: blobs[key]=z.read(member)
 report={}
 for key,data in blobs.items(): report[key]=parse(data)
 offsets=[i for i in range(len(blobs['build_a'])) if len({blobs[k][i] for k in blobs})>1]
 report['cross_member_diff_offsets']=[{'offset':hex(i),'values':{k:blobs[k][i:i+8].hex() for k in blobs},'context_a':blobs['build_a'][i-8:i+16].hex()} for i in offsets]
 out=Path(r'D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\pyd-pe-analysis.json')
 out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'member':member,'wheels':{k:{'sha256':v['sha256'],'coff_timestamp':v['coff_timestamp_hex'],'coff_utc':v['coff_timestamp_utc'],'debug_rva':v['debug_rva'],'debug_file_offset':v['debug_file_offset'],'debug_entries':v['debug_entries']} for k,v in report.items() if k in blobs},'diffs':report['cross_member_diff_offsets']},indent=2))
