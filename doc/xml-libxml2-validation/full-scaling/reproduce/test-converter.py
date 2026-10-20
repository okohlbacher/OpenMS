from pathlib import Path
import ctypes,json,random,hashlib,sys
p=Path(sys.argv[1]);lib=ctypes.CDLL(str(p));fn=lib.xmlIsolat1ToUTF8;fn.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int),ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)];fn.restype=ctypes.c_int
rng=random.Random(20261020);cases=[]
for prefix in range(18):
 for byte in range(256):
  s=b'A'*prefix+bytes([byte])+b'z'*18
  for cap in [0,1,7,8,9,len(s)-1,len(s),len(s)+1,len(s)*2]:cases.append((s,cap))
for _ in range(10000):
 n=rng.randrange(0,513);s=bytes(rng.randrange(256) if rng.random()<.2 else rng.randrange(128) for _ in range(n));cases.append((s,rng.randrange(0,2*n+2)))
h=hashlib.sha256()
for s,cap in cases:
 source=ctypes.create_string_buffer(s);dest=ctypes.create_string_buffer(b'\xa5'*(cap+32));inlen=ctypes.c_int(len(s));outlen=ctypes.c_int(cap)
 ret=fn(ctypes.addressof(dest)+16,ctypes.byref(outlen),source,ctypes.byref(inlen));expected=bytearray();used=0
 for c in s:
  encoded=chr(c).encode('utf-8')
  if len(expected)+len(encoded)>cap:break
  expected.extend(encoded);used+=1
 assert inlen.value==used and outlen.value==len(expected),(s,cap,ret,inlen.value,outlen.value)
 assert dest.raw[16:16+len(expected)]==expected
 assert dest.raw[:16]==b'\xa5'*16 and dest.raw[16+len(expected):cap+32]==b'\xa5'*(cap+16-len(expected))
 assert ret==(len(expected) if used==len(s) else -3),(s,cap,ret,used,len(expected))
 h.update(bytes(expected));h.update(str((ret,used,len(expected))).encode())
# Exact in-place ASCII: the temporary word never aliases the destination.
for n in range(65):
 buf=ctypes.create_string_buffer(b'A'*n, n+1);a=ctypes.c_int(n);b=ctypes.c_int(n);ret=fn(buf,ctypes.byref(b),buf,ctypes.byref(a));assert ret==n and buf.raw[:n]==b'A'*n
print(json.dumps({'library':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'cases':len(cases),'inplace_ascii_cases':65,'result_digest':h.hexdigest(),'all_against_python_latin1_oracle':True}))
