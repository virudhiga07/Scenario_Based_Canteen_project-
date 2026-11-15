"""Source publishing fallback; credentials are consumed only through hidden stdin."""
import json,os,subprocess,sys,termios
if sys.stdin.isatty():
 settings=termios.tcgetattr(sys.stdin);settings[3]&=~termios.ECHO;termios.tcsetattr(sys.stdin,termios.TCSANOW,settings)
print('Ready for source credential JSON on stdin (input is hidden).',flush=True)
c=json.loads(sys.stdin.readline())
env=os.environ.copy()
if c.get('auth_mode')!='work_proxy':
 env['GIT_CONFIG_COUNT']='1';env['GIT_CONFIG_KEY_0']='http.extraHeader';env['GIT_CONFIG_VALUE_0']='Authorization: Bearer '+c['token']
r=subprocess.run(['git','push',c['remote_url'],'HEAD:refs/heads/'+c.get('branch','main')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
print(r.stdout.replace(c.get('token','NO_TOKEN'),'[redacted]'))
sys.exit(r.returncode)
