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


def _normalize_allowed_email_domains(raw_value):
    """Normalize ALLOWED_EMAIL_DOMAINS config values.

    Supports YAML lists, comma/space-separated strings, or None. Returns a
    list of distinct, lowercase domain strings without leading '@'.
    """
    if not raw_value:
        return []

    # Strings may contain comma/space separated entries
    if isinstance(raw_value, str):
        candidates = [part.strip() for part in raw_value.replace(';', ',').split(',')]
    else:
        # Accept any iterable (list/tuple/set) of strings
        try:
            candidates = [str(part).strip() for part in raw_value]
        except TypeError:
            # Unsupported type; fallback to empty list
            return []

    normalized = []
    for domain in candidates:
        if not domain:
            continue
        if domain == '*':
            return ['*']
        domain = domain.lower()
        if domain.startswith('@'):
            domain = domain[1:]
        if domain:
            normalized.append(domain)

    # Preserve ordering while removing duplicates
    seen = set()
    unique_domains = []
    for domain in normalized:
        if domain not in seen:
            seen.add(domain)
            unique_domains.append(domain)
    return unique_domains

def get_config_filenames():
    if 'CONFIG_FILES' in os.environ:
        fnames = [x.strip() for x in os.environ['CONFIG_FILES'].split(':') if x.strip()]
        logger.debug('config files from CONFIG_FILES environment variable "{0}"'.format(fnames))
    else:
        fnames = ['config.yaml', 'local_config.yaml', '/etc/prosecco/local_config.yaml']
        logger.debug('default config file names, "{0}"'.format(fnames))
    return [os.path.abspath(f) for f in fnames]

# Environment variable overrides (these take precedence over yaml files)
# Note: HOSTNAME is intentionally excluded since Docker sets it to the container ID
ENV_OVERRIDES = [
    'REDIS_HOST', 'REDIS_PORT', 'REDIS_PASSWORD', 'DEBUG', 'SECRET_KEY',
    'SPOTIFY_CLIENT_ID', 'SPOTIFY_CLIENT_SECRET',
    'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
    'DEV_AUTH_EMAIL', 'YT_API_KEY', 'SOUNDCLOUD_CLIENT_ID', 'SOUNDCLOUD_CLIENT_SECRET',
    'ECHONEST_HOSTNAME',  # Use ECHONEST_HOSTNAME instead to avoid Docker conflict
    'ECHONEST_API_TOKEN',
    'ECHONEST_SPOTIFY_EMAIL',
    'ECHONEST_ADMIN_EMAILS',
    'ECHONEST_SLACK_WEBHOOK_URL',
    'ECHONEST_SYNC_INVITE_CODES',
    'NESTS_ENABLED',
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
                    if k == 'ALLOWED_EMAIL_DOMAINS':
                        v = _normalize_allowed_email_domains(v)
                    setattr(CONF, k, v)
            logger.debug('Loaded file "{0}"'.format(f))
        except Exception as e:
            print("failed", e)
            logger.debug('Failed to load file "{0}" ({1})'.format(f, str(e)))

    # Apply environment variable overrides
    for key in ENV_OVERRIDES:
        env_val = os.environ.get(key)
        if env_val is not None:
            if key == 'ECHONEST_HOSTNAME':
                config_key = 'HOSTNAME'
            elif key == 'ECHONEST_ADMIN_EMAILS':
                config_key = 'ADMIN_EMAILS'
            elif key == 'ECHONEST_SLACK_WEBHOOK_URL':
                config_key = 'SLACK_WEBHOOK_URL'
            elif key == 'ECHONEST_SYNC_INVITE_CODES':
                config_key = 'SYNC_INVITE_CODES'
            else:
                config_key = key
            if key == 'ALLOWED_EMAIL_DOMAINS':
                env_val = _normalize_allowed_email_domains(env_val)
            else:
                if isinstance(env_val, str):
                    lowered = env_val.lower()
                    # Convert string booleans
                    if lowered in ('true', '1', 'yes'):
                        env_val = True
                    elif lowered in ('false', '0', 'no'):
                        env_val = False
                    # Convert numeric strings for port
                    elif key.endswith('_PORT'):
                        try:
                            env_val = int(env_val)
                        except ValueError:
                            pass
            setattr(CONF, config_key, env_val)
            logger.debug('Override from env: {0}={1}'.format(config_key, env_val))

    # Ensure allowed domains are normalized even if only defined in YAML
    if hasattr(CONF, 'ALLOWED_EMAIL_DOMAINS'):
        setattr(CONF, 'ALLOWED_EMAIL_DOMAINS',
                _normalize_allowed_email_domains(getattr(CONF, 'ALLOWED_EMAIL_DOMAINS')))

    print("CONF", CONF)

__read_conf(*get_config_filenames())
