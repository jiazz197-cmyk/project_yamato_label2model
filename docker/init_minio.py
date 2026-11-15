"""MinIO bucket 初始化脚本。

app 容器启动时（entrypoint）幂等执行：等待 MinIO 就绪后确保
``MINIO_STORAGE_BUCKET_NAME`` 对应的 bucket 存在。与 Django settings 中的
MinIO 存储配置共用同一组环境变量。
"""

import os
import sys
import time

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

_MAX_ATTEMPTS = 30
_RETRY_INTERVAL_SECONDS = 2


def _build_client(endpoint, access_key, secret_key, region):
    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
    )


def main():
    endpoint = (os.environ.get('MINIO_STORAGE_ENDPOINT') or '').strip()
    if not endpoint:
        print('[minio-init] MINIO_STORAGE_ENDPOINT 未设置，跳过 bucket 初始化')
        return 0

    bucket = os.environ.get('MINIO_STORAGE_BUCKET_NAME', 'labelstudio')
    access_key = os.environ.get('MINIO_STORAGE_ACCESS_KEY', '')
    secret_key = os.environ.get('MINIO_STORAGE_SECRET_KEY', '')
    region = os.environ.get('MINIO_STORAGE_REGION', 'us-east-1')

    client = _build_client(endpoint, access_key, secret_key, region)
    last_error = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            client.head_bucket(Bucket=bucket)
            print(f'[minio-init] bucket 已存在: {bucket}')
            return 0
        except ClientError as exc:
            error_code = str(exc.response.get('Error', {}).get('Code', ''))
            if error_code in ('404', 'NoSuchBucket', 'NotFound'):
                try:
                    client.create_bucket(Bucket=bucket)
                    print(f'[minio-init] 已创建 bucket: {bucket}')
                    return 0
                except (BotoCoreError, ClientError) as create_exc:
                    last_error = create_exc
            else:
                last_error = exc
        except BotoCoreError as exc:
            last_error = exc

        print(
            f'[minio-init] 等待 MinIO 就绪（第 {attempt}/{_MAX_ATTEMPTS} 次）: {last_error}',
            file=sys.stderr,
        )
        time.sleep(_RETRY_INTERVAL_SECONDS)

    required = os.environ.get('MINIO_INIT_REQUIRED', '0') == '1'
    print(f'[minio-init] bucket 初始化失败: {last_error}', file=sys.stderr)
    if required:
        return 1
    print('[minio-init] MINIO_INIT_REQUIRED=0，告警后继续启动 app', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
