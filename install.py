#!/usr/bin/env python3
"""Install the macOS login service. Other platforms can run server.py directly."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
from server import DEFAULT_STATE, DEFAULT_ARCHIVE, ensure_token
from config_store import ConfigStore


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,default=DEFAULT_STATE)
    parser.add_argument('--archive',type=Path,default=DEFAULT_ARCHIVE)
    parser.add_argument('--host',default='0.0.0.0')
    parser.add_argument('--port',type=int,default=7076)
    parser.add_argument('--with-apple',action='store_true',help='build the Apple archiver if it is not installed')
    args=parser.parse_args()
    if sys.platform!='darwin':
        parser.error('launchd installation is macOS-only; run python3 server.py on Linux/Windows')
    root=Path(__file__).resolve().parent
    state=args.state.expanduser().resolve();ensure_token(state)
    config=ConfigStore(state,args.archive)
    # Stop legacy periodic Android job; one service now owns all schedules.
    old='local.screentime-web.android-sync'
    old_plist=Path.home()/'Library/LaunchAgents'/(old+'.plist')
    subprocess.run(['launchctl','bootout',f'gui/{os.getuid()}/{old}'],capture_output=True)
    if old_plist.exists():
        backup=state/'installation-backups';backup.mkdir(mode=0o700,parents=True,exist_ok=True)
        shutil.move(str(old_plist),str(backup/(old+'.plist')))
    from apple_install import install
    if install(state,build_if_missing=args.with_apple,archive=args.archive.expanduser().resolve()):
        if not any(s['type']=='apple' for s in config.load()['sources']):
            config.save_source({'id':'apple','name':'Apple 归档（本机与 iCloud 设备）','type':'apple','schedule_mode':'inherit'})
    logs=Path.home()/'Library/Logs/ScreenTimeWeb';logs.mkdir(parents=True,exist_ok=True)
    agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
    label='local.screentime-web';plist=agents/(label+'.plist')
    value={'Label':label,'ProgramArguments':[sys.executable,str(root/'server.py'),'--host',args.host,'--port',str(args.port),
            '--state',str(state),'--archive',str(args.archive.expanduser().resolve())],
           'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
           'StandardOutPath':str(logs/'server.log'),'StandardErrorPath':str(logs/'server.log'),
           'EnvironmentVariables':{'PYTHONUNBUFFERED':'1'}}
    target=f'gui/{os.getuid()}/{label}'
    subprocess.run(['launchctl','bootout',target],capture_output=True)
    for _ in range(40):
        if subprocess.run(['launchctl','print',target],capture_output=True).returncode:break
        time.sleep(.1)
    with plist.open('wb') as f:plistlib.dump(value,f)
    subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(plist)],check=True)
    print(f'Installed http://127.0.0.1:{args.port}')
    print('Token stored privately at: '+str(state/'access-token'))
    if args.with_apple:print('Grant Full Disk Access to the archiver, then run Apple sync from the Web UI.')


if __name__=='__main__':main()
