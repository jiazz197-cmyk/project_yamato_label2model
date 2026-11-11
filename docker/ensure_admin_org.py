"""为 createsuperuser 创建的管理员补齐组织成员关系（开发环境辅助脚本）。

Label Studio 的登录流程要求用户至少属于一个组织（``Organization.find_by_user``），
而 ``manage.py createsuperuser`` 不会创建组织/成员关系。通过 Web 注册的用户会自动
建组织；本脚本用于命令行创建超管后的补齐，幂等：

    docker compose exec app python docker/ensure_admin_org.py admin@example.com
"""

import os
import sys

import django

# 让 core.* / users.* 等 Django 应用可被导入（与 manage.py 的 sys.path 处理一致）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'label_studio'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.label_studio')
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from organizations.models import Organization, OrganizationMember  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print('用法: python docker/ensure_admin_org.py <email>', file=sys.stderr)
        return 2

    email = argv[1]
    user_model = get_user_model()
    try:
        user = user_model.objects.get(email=email)
    except user_model.DoesNotExist:
        print(f'用户不存在: {email}', file=sys.stderr)
        return 1

    membership = OrganizationMember.objects.filter(user=user).select_related('organization').first()
    if membership:
        organization = membership.organization
        print(f'用户 {email} 已属于组织 {organization.title}（id={organization.id}）')
    else:
        organization = Organization.objects.first()
        if organization is None:
            organization = Organization.create_organization(title='Default Organization', created_by=user)
            print(f'已创建组织 {organization.title}（id={organization.id}）')
        else:
            OrganizationMember.objects.create(user=user, organization=organization)
            print(f'已把 {email} 加入组织 {organization.title}（id={organization.id}）')

    user.active_organization = organization
    user.save(update_fields=['active_organization'])
    print(f'active_organization={organization.id}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
