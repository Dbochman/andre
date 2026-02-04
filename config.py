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

def __read_conf(*files):
    for f in files:
        print f
        try:
            data = yaml.load(open(f))
            print data
            for k,v in data.items():
                print k, v
                setattr(CONF, k, v)
            logger.debug('Loaded file "{0}"'.format(f))
        except Exception as e:
            print "failed", e
            logger.debug('Failed to load file "{0}" ({1})'.format(f, str(e)))
    print "CONF", CONF

__read_conf(*get_config_filenames())
