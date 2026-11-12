"""Build the optional MIT-licensed Apple archiver; keep existing signed binaries intact."""
from pathlib import Path
import os
import plistlib
import shutil
import subprocess
import sys
import time

LABEL='io.github.tobias-x.screentime-archiver'


def build_archiver(output):
    root=Path(__file__).resolve().parent
    build=output.parent;build.mkdir(parents=True,exist_ok=True)
    arch=subprocess.check_output(['uname','-m'],text=True).strip()
    args=['swiftc','-O','-target',arch+'-apple-macos14.0']
    stray=Path('/Library/Developer/CommandLineTools/usr/include/swift/module.modulemap')
    if stray.exists():
        empty=build/'empty.modulemap';empty.write_text('')
        overlay=build/'overlay.json'
        import json
        overlay.write_text(json.dumps({'version':0,'case-sensitive':'false','roots':[{'type':'file','name':str(stray),'external-contents':str(empty)}]}))
        args+=['-vfsoverlay',str(overlay),'-Xcc','-ivfsoverlay','-Xcc',str(overlay)]
    subprocess.run(args+['-o',str(output)]+[str(p) for p in sorted((root/'vendor/apple-archiver').glob('*.swift'))],check=True)
    subprocess.run(['codesign','--force','--sign','-','--identifier',LABEL,str(output)],check=True)


def install(state,build_if_missing=False,archive=None):
    if sys.platform!='darwin':raise RuntimeError('Apple collection requires macOS 14+')
    version=int(subprocess.check_output(['sw_vers','-productVersion'],text=True).split('.')[0])
    if version<14:raise RuntimeError('macOS 14+ required')
    root=Path(__file__).resolve().parent
    support=Path.home()/'Library/Application Support/ScreenTimeArchive'
    binary=support/'bin/screentime-archiver'
    if not binary.exists():
        if not build_if_missing:return False
        output=root/'.build/apple/screentime-archiver'
        build_archiver(output)
        binary.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(output,binary);binary.chmod(0o755)
    agents=Path.home()/'Library/LaunchAgents';agents.mkdir(parents=True,exist_ok=True)
    plist=agents/(LABEL+'.plist')
    if plist.exists():
        backup=Path(state)/'installation-backups';backup.mkdir(mode=0o700,parents=True,exist_ok=True)
        dest=backup/(LABEL+'.original.plist')
        if not dest.exists():shutil.copy2(plist,dest)
    logs=Path.home()/'Library/Logs/ScreenTimeArchive';logs.mkdir(parents=True,exist_ok=True)
    arguments=[str(binary)]+(['--archive',str(archive)] if archive is not None else [])
    config={'Label':LABEL,'ProgramArguments':arguments,'RunAtLoad':False,'ProcessType':'Background',
            'LowPriorityIO':True,'StandardOutPath':str(logs/'archiver.log'),'StandardErrorPath':str(logs/'archiver.log')}
    target=f'gui/{os.getuid()}/{LABEL}'
    subprocess.run(['launchctl','bootout',target],capture_output=True)
    for _ in range(40):
        if subprocess.run(['launchctl','print',target],capture_output=True).returncode:break
        time.sleep(.1)
    with plist.open('wb') as f:plistlib.dump(config,f)
    subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(plist)],check=True)
    return True
