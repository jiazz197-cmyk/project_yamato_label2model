"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license."""

import json
import os

import environ

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    environ.Env.read_env(_env_file)

from core.settings.base import *  # noqa
from core.utils.secret_key import generate_secret_key_if_missing

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = generate_secret_key_if_missing(BASE_DATA_DIR)

DJANGO_DB = get_env('DJANGO_DB', DJANGO_DB_SQLITE)
DATABASES = {'default': DATABASES_ALL[DJANGO_DB]}

MIDDLEWARE.append('organizations.middleware.DummyGetSessionMiddleware')
MIDDLEWARE.append('core.middleware.UpdateLastActivityMiddleware')
if INACTIVITY_SESSION_TIMEOUT_ENABLED:
    MIDDLEWARE.append('core.middleware.InactivitySessionTimeoutMiddleWare')

ADD_DEFAULT_ML_BACKENDS = False

LOGGING['root']['level'] = get_env('LOG_LEVEL', 'WARNING')

DEBUG = get_bool_env('DEBUG', False)

DEBUG_PROPAGATE_EXCEPTIONS = get_bool_env('DEBUG_PROPAGATE_EXCEPTIONS', False)

SESSION_COOKIE_SECURE = get_bool_env('SESSION_COOKIE_SECURE', False)

SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

SENTRY_DSN = get_env('SENTRY_DSN', 'https://68b045ab408a4d32a910d339be8591a4@o227124.ingest.sentry.io/5820521')
SENTRY_ENVIRONMENT = get_env('SENTRY_ENVIRONMENT', 'opensource')

FRONTEND_SENTRY_DSN = get_env(
    'FRONTEND_SENTRY_DSN', 'https://5f51920ff82a4675a495870244869c6b@o227124.ingest.sentry.io/5838868'
)
FRONTEND_SENTRY_ENVIRONMENT = get_env('FRONTEND_SENTRY_ENVIRONMENT', 'opensource')

EDITOR_KEYMAP = json.dumps(get_env('EDITOR_KEYMAP'))

from label_studio import __version__
from label_studio.core.utils import sentry

sentry.init_sentry(release_name='yamato', release_version=__version__)

# we should do it after sentry init
from label_studio.core.utils.common import collect_versions

versions = collect_versions()

# in Yamato Community version, feature flags are always ON
FEATURE_FLAGS_DEFAULT_VALUE = True
# or if file is not set, default is using offline mode
FEATURE_FLAGS_OFFLINE = get_bool_env('FEATURE_FLAGS_OFFLINE', True)

FEATURE_FLAGS_FILE = get_env('FEATURE_FLAGS_FILE', 'feature_flags.json')
FEATURE_FLAGS_FROM_FILE = True
try:
    from core.utils.io import find_node

    find_node('label_studio', FEATURE_FLAGS_FILE, 'file')
except IOError:
    FEATURE_FLAGS_FROM_FILE = False

STORAGE_PERSISTENCE = get_bool_env('STORAGE_PERSISTENCE', True)

REDIS_ENABLED = get_bool_env('REDIS_ENABLED', False)
if REDIS_ENABLED:
    _REDIS_HOST = get_env('REDIS_HOST', 'localhost')
    _REDIS_PORT = int(get_env('REDIS_PORT', 6379))
    _REDIS_DB = int(get_env('REDIS_DB', 0))
    RQ_QUEUES = {
        q: {
            'HOST': _REDIS_HOST,
            'PORT': _REDIS_PORT,
            'DB': _REDIS_DB,
            'DEFAULT_TIMEOUT': int(get_env('RQ_DEFAULT_TIMEOUT', 180)),
        }
        for q in ('critical', 'high', 'default', 'low')
    }
    # Celery 任务队列的 broker/result backend 地址。
    # 复用上面同一份 Redis 连接（RQ_QUEUES 与 Celery 共用），
    # 由 .env 的 REDIS_HOST/REDIS_PORT/REDIS_DB 派生；REDIS_DB 缺省为 0。
    # 仅当 REDIS_ENABLED=True 时定义——celery_app.py 侧用 getattr 兜底。
    CELERY_BROKER_URL = f'redis://{_REDIS_HOST}:{_REDIS_PORT}/{_REDIS_DB}'

# === Training (Sub-Issue 2) ===
# 本地预置模型根目录：上传的模型与训练产物统一存放于此
# （模型只走本地盘，不经 MinIO；默认 data/models 相对项目根解析）。
LOCAL_MODEL_ROOT = get_env('LOCAL_MODEL_ROOT', os.path.join(BASE_DATA_DIR, 'models'))
# 与 base.py 中 MEDIA_ROOT 同款模式：settings 加载期即建目录，避免运行时缺失。
os.makedirs(LOCAL_MODEL_ROOT, exist_ok=True)
# 训练产物子目录名：完整产物路径为 <LOCAL_MODEL_ROOT>/<该前缀>/<job_id>/。
TRAINING_ARTIFACTS_STORAGE_PREFIX = get_env('TRAINING_ARTIFACTS_STORAGE_PREFIX', 'trained')
# 单模型上传大小上限（字节，默认 2GB，百 MB 级模型留余量；todo 17 分片上传使用）。
TRAINING_UPLOAD_MAX_SIZE = int(get_env('TRAINING_UPLOAD_MAX_SIZE', 2 * 1024 ** 3))
# 分片上传每片大小（字节，默认 8MB；todo 17 使用）。
TRAINING_UPLOAD_CHUNK_SIZE = int(get_env('TRAINING_UPLOAD_CHUNK_SIZE', 8 * 1024 ** 2))
# Sample subset 随机取样数（todo 5 数据集子集提取使用）。
TRAINING_SAMPLE_SIZE = int(get_env('TRAINING_SAMPLE_SIZE', 100))
# FastAPI predictor 侧车监听端口（todo 9 runpredictionservice 使用）。
PREDICTOR_PORT = int(get_env('PREDICTOR_PORT', 8990))
# Redis pub/sub 进度推送 channel 前缀：实际 channel 为 <前缀>:<job_id>（todo 8/9 使用）。
TRAINING_PROGRESS_REDIS_CHANNEL = get_env('TRAINING_PROGRESS_REDIS_CHANNEL', 'training:progress')
