"""Isolated integration check: Docker image must contain Caddy 2.10+ and Python.

Build once:  docker build -f tests/docker/Dockerfile -t ownline-caddy-smoke:final .
Run explicitly with: python3 tests/first_login_caddy_smoke.py
No host data, ports, real credentials or network are used.
"""
import base64
import io
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
image = 'ownline-caddy-smoke:final'
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
    for path in [ROOT / 'server/admin.py', ROOT / 'server/reset_admin_password.py',
                 ROOT / 'server/nodekit', ROOT / 'server/providers']:
        archive.add(path, arcname=path.relative_to(ROOT / 'server'),
                    filter=lambda info: None if '__pycache__' in info.name else info)
    archive.add(ROOT / 'web/change-password.html', arcname='change-password.html')
    archive.add(ROOT / 'deploy/install.sh', arcname='install.sh')
payload = base64.b64encode(buffer.getvalue()).decode()

script = r'''set -eu
mkdir -p /etc/caddy /opt/web /opt/web-data /tmp/testbin
printf %s PAYLOAD | base64 -d | tar xz -C /opt/web
printf '<html>VPN-OwnLine</html>' >/opt/web/index.html
printf '[{"name":"test","health":"ok","role":"exit","source":"builtin","host":"198.51.100.1","port":443,"uuid":"11111111-1111-4111-8111-111111111111","pbk":"PUB","sid":"abcd1234","sni":"www.example.com"}]' >/opt/web-data/nodes.json
printf '{"sub_token":"1234567890abcdef"}' >/opt/web-data/settings.json
printf '{}' >/opt/web-data/status.json
printf '#!/bin/sh\nexec caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile\n' >/tmp/testbin/systemctl
chmod +x /tmp/testbin/systemctl
export PATH="/tmp/testbin:$PATH"
python3 - <<'INNER'
import subprocess
from pathlib import Path
script = Path('/opt/web/install.sh').read_text()
template = script.split('cat > "$CADDY_STAGED" << CADDYEOF\n', 1)[1].split('\nCADDYEOF', 1)[0]
old = subprocess.run(['caddy','hash-password'],input=b'test-old-password-only\n',stdout=subprocess.PIPE,check=True).stdout.decode().strip()
config = template.replace('$SETUP_JOB','disposable').replace('$PASS_HASH',old).replace('${DOMAIN}','localhost').replace('$TLS_DIRECTIVE','tls internal')+'\n'
Path('/etc/caddy/Caddyfile').write_text(config)
Path('/opt/web-data/.initial-password-required').touch()
INNER
python3 /opt/web/admin.py >/tmp/admin-log 2>&1 &
export ADMIN_PID=$!
caddy start --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy-log 2>&1
python3 - <<'INNER'
import base64,concurrent.futures,http.client,json,socket,ssl
ctx = ssl._create_unverified_context()
def call(path, password='test-old-password-only', method='GET', body=None):
    conn = http.client.HTTPSConnection('localhost',8443,context=ctx,timeout=30)
    conn._create_connection = lambda address,timeout,*a:socket.create_connection(('127.0.0.1',8443),timeout,*a)
    headers = {'Host':'localhost:8443'}
    if password is not None:
        headers['Authorization'] = 'Basic '+base64.b64encode(('admin:'+password).encode()).decode()
    if body is not None:
        body = json.dumps(body).encode(); headers.update({'Content-Type':'application/json','Origin':'https://localhost:8443'})
    conn.request(method,path,body=body,headers=headers)
    response=conn.getresponse(); status=response.status; location=response.getheader('Location'); data=response.read(); conn.close()
    return status,location,data

assert call('/',None)[0] == 401
for path in ('/', '/api/nodes', '/api/backup', '/status.json'):
    result=call(path); assert result[:2] == (303,'/change-password'), (path,result[:2])
assert call('/change-password')[0] == 200
assert call('/api/password/state')[0] == 200
assert call('/s/1234567890abcdef/sr',password=None)[0] == 200
bad={'current':'incorrect-password','new':'test-new-password-only','confirm':'test-new-password-only'}
assert call('/api/password/change',method='POST',body=bad)[0] == 403
conn=http.client.HTTPSConnection('localhost',8443,context=ctx,timeout=30)
conn._create_connection=lambda address,timeout,*a:socket.create_connection(('127.0.0.1',8443),timeout,*a)
cross=json.dumps({'current':'test-old-password-only','new':'test-new-password-only','confirm':'test-new-password-only'})
conn.request('POST','/api/password/change',body=cross,headers={'Host':'localhost:8443','Origin':'https://attacker.example','Content-Type':'application/json','Authorization':'Basic '+base64.b64encode(b'admin:test-old-password-only').decode()})
response=conn.getresponse();assert response.status == 403;response.read();conn.close()
payload={'current':'test-old-password-only','new':'test-new-password-only','confirm':'test-new-password-only'}
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(lambda _:call('/api/password/change',method='POST',body=payload)[0],range(2)))
assert results.count(200) == 1 and any(x in (401,403,409) for x in results), results
assert call('/',password='test-old-password-only')[0] == 401
assert call('/',password='test-new-password-only')[0] == 200
assert call('/status.json',password='test-new-password-only')[0] == 200
assert call('/api/nodes',password='test-new-password-only')[0] == 200
import importlib.util,os,signal,subprocess,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('reset_tool','/opt/web/reset_admin_password.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
marker=Path('/opt/web-data/.initial-password-required');marker.touch()
# Model a crash after changing the hash but before clearing the durable marker.
tool.reset(Path('/etc/caddy/Caddyfile'),'test-crash-password-only')
os.kill(int(os.environ['ADMIN_PID']),signal.SIGTERM)
time.sleep(.5)
subprocess.Popen(['python3','/opt/web/admin.py'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
time.sleep(.7)
assert call('/',password='test-crash-password-only')[:2] == (303,'/change-password')
recovery={'current':'test-crash-password-only','new':'test-recovered-password-only','confirm':'test-recovered-password-only'}
assert call('/api/password/change',password='test-crash-password-only',method='POST',body=recovery)[0] == 200
assert call('/',password='test-recovered-password-only')[0] == 200
print('PASS: real Caddy gate, origin/bypass, subscription, concurrency and crash recovery')
INNER
'''.replace('PAYLOAD', payload)
result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--entrypoint',
                         'bash', image], input=script, text=True, check=False)
raise SystemExit(result.returncode)
