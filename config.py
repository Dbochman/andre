import yaml, os, os.path, pprint, logging

class _Configuration(object):
    def __repr__(self):
        return pprint.pformat(dict((k, getattr(self, k))
                                for k in dir(self) if not k.startswith('_') and k != 'get'))

    def __getattr__(self, name):
        return None

    def get(self, key, default):
        if hasattr(self, key):
            return getattr(self, key)
        return default

CONF = _Configuration()
logger = logging.getLogger(__name__)

def get_config_filenames():
    if 'CONFIG_FILES' in os.environ:
        fnames = [x.strip() for x in os.environ['CONFIG_FILES'].split(':') if x.strip()]
        logger.debug('config files from CONFIG_FILES environment variable "{0}"'.format(fnames))
    else:
        fnames = ['config.yaml', 'local_config.yaml', '/etc/prosecco/local_config.yaml']
        logger.debug('default config file names, "{0}"'.format(fnames))
    return [os.path.abspath(f) for f in fnames]

# Environment variable overrides (these take precedence over yaml files)
ENV_OVERRIDES = [
    'REDIS_HOST', 'REDIS_PORT', 'DEBUG', 'SECRET_KEY', 'HOSTNAME',
    'SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET',
    'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
    'DEV_AUTH_EMAIL', 'YT_API_KEY', 'SOUNDCLOUD_CLIENT_ID'
]

def __read_conf(*files):
    for f in files:
        print(f)
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if data:
                print(data)
                for k, v in data.items():
                    print(k, v)
                    setattr(CONF, k, v)
            logger.debug('Loaded file "{0}"'.format(f))
        except Exception as e:
            print("failed", e)
            logger.debug('Failed to load file "{0}" ({1})'.format(f, str(e)))

    # Apply environment variable overrides
    for key in ENV_OVERRIDES:
        env_val = os.environ.get(key)
        if env_val is not None:
            # Convert string booleans
            if env_val.lower() in ('true', '1', 'yes'):
                env_val = True
            elif env_val.lower() in ('false', '0', 'no'):
                env_val = False
            # Convert numeric strings for port
            elif key.endswith('_PORT'):
                try:
                    env_val = int(env_val)
                except ValueError:
                    pass
            setattr(CONF, key, env_val)
            logger.debug('Override from env: {0}={1}'.format(key, env_val))

    print("CONF", CONF)

__read_conf(*get_config_filenames())
