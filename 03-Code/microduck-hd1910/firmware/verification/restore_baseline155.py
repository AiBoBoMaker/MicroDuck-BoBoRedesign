from pathlib import Path
import hashlib,json,tarfile
B=Path(__file__).resolve().parent
archive=B/'work/Microduck-Console-R17-v1.0.154/updates/Microduck-Robotd-FT6-R17.tar.gz'
metadata=json.loads((B/'work/Microduck-Console-R17-v1.0.154/BUILD_MANIFEST.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert metadata['console_version']=='1.0.154' and sha(archive)==metadata['service_package_sha256']
destination=B/'firmware155-base';assert not destination.exists();destination.mkdir()
with tarfile.open(archive,'r:gz') as tar:
 members=tar.getmembers();names=[m.name for m in members];assert len(names)==len(set(names))
 for m in members:
  assert Path(m.name).parts[0]=='Microduck-Robotd-FT6-R17' and '..' not in Path(m.name).parts
  assert m.isfile() or m.isdir()
 tar.extractall(destination,filter='data')
root=destination/'Microduck-Robotd-FT6-R17'
rows={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(root.rglob('*')) if p.is_file()}
declarations=dict(line.split('  ',1)[::-1] for line in (root/'SHA256SUMS').read_text().splitlines())
assert set(declarations)==set(rows)-{'SHA256SUMS'}
assert all(rows[n]['sha256']==expected for n,expected in declarations.items())
record={'archive':str(archive),'archive_sha256':sha(archive),'declared_original_checksums_verified':True,'destination':str(root),'files':rows,'hardware_tested':False}
(B/'baseline-restored155.json').write_text(json.dumps(record,indent=2)+'\n')
print('Verified and restored',len(rows),'original v154 payload files')
