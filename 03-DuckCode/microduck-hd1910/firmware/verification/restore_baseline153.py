"""Recover baseline bytes directly from the verified, original tar stream."""
from pathlib import Path
import hashlib
import json
import tarfile

BASE=Path(__file__).resolve().parent
ARCHIVE=BASE/'work/Microduck-Console-R17-v1.0.151/updates/Microduck-Robotd-FT6-R17.tar.gz'
DESTINATION=BASE/'firmware153-base/Microduck-Robotd-FT6-R17'
EXPECTED_ARCHIVE='f5461e5e1385a38c7b99b767965e20a193bb9da49a857b8533a473fc5a6ca265'

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def restore():
    assert digest(ARCHIVE)==EXPECTED_ARCHIVE,'Original firmware archive checksum differs'
    if DESTINATION.exists():raise ValueError('Use a fresh destination')
    with tarfile.open(ARCHIVE,'r:gz') as archive:
        members=archive.getmembers()
        manifest=archive.extractfile(DESTINATION.name+'/SHA256SUMS').read().decode()
        expected={}
        for row in manifest.splitlines():
            sha,separator,name=row.partition('  ')
            assert separator and len(sha)==64 and name not in expected
            expected[name]=sha
        recovered={}
        for member in members:
            relative=Path(member.name).parts
            assert relative[0]==DESTINATION.name and '..' not in relative
            if member.isdir():continue
            assert member.isfile(),'Baseline contains an unexpected link or special file'
            name=Path(*relative[1:]).as_posix();assert name not in recovered
            with archive.extractfile(member) as stream:raw=stream.read()
            actual=hashlib.sha256(raw).hexdigest()
            assert len(raw)==member.size,(name,'short archive read')
            if name!='SHA256SUMS':assert expected.get(name)==actual,(name,'original manifest mismatch')
            target=DESTINATION/name;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('wb') as stream:
                assert stream.write(raw)==len(raw)
            target.chmod(member.mode&0o777)
            assert target.stat().st_size==member.size and digest(target)==actual,(name,'short restored write')
            recovered[name]={'bytes':member.size,'sha256':actual}
        assert set(recovered)==set(expected)|{'SHA256SUMS'}
    report={'archive':str(ARCHIVE),'archive_sha256':EXPECTED_ARCHIVE,
            'declared_original_checksums_verified':True,'files':recovered,
            'destination':str(DESTINATION),'hardware_tested':False}
    (BASE/'baseline-restored153.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Restored and verified',len(recovered),'baseline files')

if __name__=='__main__':restore()
