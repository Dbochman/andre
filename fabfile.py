import os.path

from fabric.api import sudo, run, put, env, cd
from fabric.contrib.files import exists
from fabric.colors import red, yellow


env.user = 'ubuntu'

PACKAGES = ('wget', 'vim', 'libevent-dev', 'htop', 'redis-server',
            'python-dev', 'build-essential', 'supervisor', 'git',
            'libjpeg-dev', 'libfreetype6-dev', 'zlib1g-dev',
            'python-scipy', 'python-numpy', 'python-imaging',
            'wamerican-huge',
            'python-pip', 'libatlas-base-dev', 'gfortran')

def notice(s):
    print(red('### ')+yellow(s, bold=True))

if not env.hosts:
    notice('Automatically setting host to itsprosecco.sandpit.us')
    env.hosts = ['itsprosecco.sandpit.us']

env.key_filename = '/etc/echonest/aws_credentials/gsg-keypair-120810.pem'
APP_ROOT = '/opt/prosecco'

THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def update_system_packages():
    notice('Updating System Packages')
    sudo('apt-get -y update')
    sudo('apt-get -y dist-upgrade')
    sudo('apt-get -y install {0}'.format(' '.join(PACKAGES)))

def update_repo():
    notice('Updating Repo from GitHub')
    if not exists(APP_ROOT):
        sudo('mkdir -p {0}'.format(APP_ROOT))
    sudo('chown -R ubuntu:ubuntu {0}'.format(APP_ROOT))
    put(os.path.join(THIS_DIR, 'github_deploy_key'),
            '/home/ubuntu/.ssh/id_rsa')
    sudo('chmod 600 /home/ubuntu/.ssh/id_rsa')
    if not exists(os.path.join(APP_ROOT, '.git')):
        print(red('FIRST CHECKOUT'))
        with cd(APP_ROOT):
            run('git clone git@github.com:echonest/prosecco .')
    with cd(APP_ROOT):
        run('git pull')

def update_python_packages():
    notice('Updating Python Packages')
    sudo('pip install -r {0}'.format(os.path.join(APP_ROOT,'requirements.txt')))

def update_os_conf():
    notice('Updating OS Configuration')
    with cd(APP_ROOT):
        sudo('cp -r etc /')
    # what if we just added/changed supervisor? got to reread/update
    sudo('supervisorctl reread')
    sudo('supervisorctl update')

def restart_services():
    sudo('supervisorctl restart all')

def from_orbit():
    notice('FROM ORBIT')
    sudo('redis-cli flushall')
    restart_services()

def big():
    notice('BIG UPDATE')
    update_system_packages()
    update_repo()
    update_python_packages()
    update_os_conf()
    restart_services()

def small():
    notice('SMALL UPDATE')
    update_repo()
    restart_services()
