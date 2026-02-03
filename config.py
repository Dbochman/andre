import yaml, os, os.path, pprint, logging

def _parse_env_bool(value):
    if value is None:
        return None
    return value.strip().lower() in ("1", "true", "yes", "y", "on")

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

def __read_conf(*files):
    for f in files:
        try:
            with open(f, "r") as fh:
                data = yaml.safe_load(fh) or {}
            for k, v in data.items():
                setattr(CONF, k, v)
            logger.debug('Loaded file "{0}"'.format(f))
        except Exception as e:
            logger.debug('Failed to load file "{0}" ({1})'.format(f, str(e)))

    # Apply selected environment overrides after file load.
    env_map = {
        "DEBUG": ("DEBUG", _parse_env_bool),
        "DEV_AUTH_EMAIL": ("DEV_AUTH_EMAIL", str),
        "REDIS_HOST": ("REDIS_HOST", str),
        "REDIS_PORT": ("REDIS_PORT", int),
        "HOSTNAME": ("HOSTNAME", str),
    }
    for env_key, (conf_key, cast) in env_map.items():
        if env_key in os.environ:
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            try:
                val = cast(raw) if cast is not None else raw
                setattr(CONF, conf_key, val)
            except Exception as e:
                logger.debug('Failed to apply env override %s: %s', env_key, e)

__read_conf(*get_config_filenames())
