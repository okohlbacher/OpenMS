from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[2];source=root/'benchmark-data/large.mzML';dest=root/'benchmark-data/large-utf8.mzML'
with source.open('rb') as f:header=f.readline()
old=b'encoding="ISO-8859-1"';new=b'encoding="UTF-8"';assert header.count(old)==1
replacement=header.replace(old,new+b' '*(len(old)-len(new)));assert len(header)==len(replacement)
a=hashlib.sha256();b=hashlib.sha256();ascii_only=True
with source.open('rb') as i,dest.open('wb') as o:
 original=i.readline();assert original==header;o.write(replacement);a.update(header);b.update(replacement)
 while block:=i.read(4*1024*1024):
  assert block.isascii(),'Non-ASCII body needs transcoding; declaration-only experiment invalid'
  o.write(block);a.update(block);b.update(block)
assert source.stat().st_size==dest.stat().st_size
record={'original':str(source),'utf8_copy':str(dest),'original_sha256':a.hexdigest(),'utf8_sha256':b.hexdigest(),'bytes':source.stat().st_size,'original_header':header.decode().rstrip(),'utf8_header':replacement.decode().rstrip(),'only_first_line_changed':True,'unchanged_byte_length':True,'entire_body_ascii':ascii_only,'index_offsets_preserved':True,'method':'Declaration-only ISO-8859-1 to UTF-8, pad with spaces, identical remaining bytes; original input retained.'}
(root/'results/encoding-followup/macos/input-preparation.json').write_text(json.dumps(record,indent=2)+'\n');print(record)
