"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license."""

# ============================================================================
# 【注释版】对应 commit ada930cea9e72e045e86d1c3744e8e032c280148，仅供理解，请勿提交。
# 本 commit 对该文件的改动 = AllPermissions 里新增 3 个 training.* 权限点（★ 处）。
# 整个文件是全站"权限点注册表"：
#   1) AllPermissions：pydantic 模型，集中声明所有权限点字符串；
#   2) all_permissions：单例实例，视图通过 all_permissions.xxx 引用；
#   3) ViewClassPermission：按 HTTP 方法声明权限的 pydantic 模型；
#   4) 底部循环：把所有权限点注册进 rules 库（谓词 = is_authenticated）。
# 关于"本代码库中 permission_required 属性不被 DRF 消费"的完整说明见 README §4。
# ============================================================================

import logging  # noqa: I001
# 日志（noqa: I001 = 抑制 isort 的导入顺序告警，上游原样保留）。
from typing import Optional
# 下面 ViewClassPermission 的字段类型注解用 Optional[str]。

from pydantic import BaseModel, ConfigDict
# pydantic v2：
# - BaseModel：声明式数据模型（字段 + 默认值 + 校验）；
# - ConfigDict：模型配置。

import rules
# `rules` 库（Python 权限规则引擎）：提供 add_perm/has_perm 等。
# 本文件用它注册"权限名 → 判定谓词"的映射。

logger = logging.getLogger(__name__)
# 模块 logger（本文件目前没有直接打日志，惯例声明）。


class AllPermissions(BaseModel):
    # 全站权限点清单。每个字段 = 一个权限点，字段名 = 代码里的引用名，
    # 字段值 = 权限点的规范字符串（如 'projects.view'）。
    model_config = ConfigDict(protected_namespaces=('__.*__', '_.*'))
    # pydantic v2 默认把 'model_' 前缀的字段名当"保留内部属性"报警告；
    # 这里放宽为只保留 '__.*__' 和 '_.*' 前缀，让 model_provider_connection_* 这类
    # 以 model_ 开头的业务字段名合法（业务命名巧合撞上了 pydantic 的保留前缀）。

    organizations_create: str = 'organizations.create'
    # 组织 app 的 5 个权限点（建/看/改/删/邀请）：
    organizations_view: str = 'organizations.view'
    organizations_change: str = 'organizations.change'
    organizations_delete: str = 'organizations.delete'
    organizations_invite: str = 'organizations.invite'
    projects_create: str = 'projects.create'
    # 项目 app 的 5 个权限点：
    projects_view: str = 'projects.view'
    projects_change: str = 'projects.change'
    projects_delete: str = 'projects.delete'
    projects_reset_cache: str = 'projects.reset_cache'
    tasks_create: str = 'tasks.create'
    # 任务 app 的 4 个权限点：
    tasks_view: str = 'tasks.view'
    tasks_change: str = 'tasks.change'
    tasks_delete: str = 'tasks.delete'
    views_reset: str = 'views.reset'
    # 数据管理视图（列表视图配置）重置：
    annotations_create: str = 'annotations.create'
    # 标注 app 的 4 个权限点：
    annotations_view: str = 'annotations.view'
    annotations_change: str = 'annotations.change'
    annotations_delete: str = 'annotations.delete'
    actions_perform: str = 'actions.perform'
    predictions_any: str = 'predictions.any'
    # 杂项：操作执行 / 预测任意操作 / 头像任意操作：
    avatar_any: str = 'avatar.any'
    labels_create: str = 'labels.create'
    # 标签管理 app 的 4 个权限点：
    labels_view: str = 'labels.view'
    labels_change: str = 'labels.change'
    labels_delete: str = 'labels.delete'
    models_create: str = 'models.create'
    # ML 模型（MLBackend）的 4 个权限点：
    models_view: str = 'models.view'
    models_change: str = 'models.change'
    models_delete: str = 'models.delete'
    training_create: str = 'training.create'
    # ★★★ 本次 commit 新增：training app 的 3 个权限点。
    # 字符串命名沿用 '<app>.<动作>' 惯例；
    # 底部循环会把它们注册进 rules（谓词 = is_authenticated）。
    training_view: str = 'training.view'
    training_cancel: str = 'training.cancel'
    # 'training.cancel' 单独成点（而不是并入 change）：
    # 为将来"取消权限独立授予"（如普通成员不能取消别人的任务）留扩展位。
    model_provider_connection_create: str = 'model_provider_connection.create'
    # 模型提供商连接的 4 个权限点：
    model_provider_connection_view: str = 'model_provider_connection.view'
    model_provider_connection_change: str = 'model_provider_connection.change'
    model_provider_connection_delete: str = 'model_provider_connection.delete'
    webhooks_view: str = 'webhooks.view'
    # webhook 的 2 个权限点：
    webhooks_change: str = 'webhooks.change'
    users_token_any: str = 'users.token.any'
    # 用户 API token 任意操作：
    storages_view: str = 'storages.view'
    # 存储（io_storages）的 3 个权限点：
    storages_change: str = 'storages.change'
    storages_sync: str = 'storages.sync'
    views_view: str = 'views.view'
    # 数据管理视图 app 的 4 个权限点：
    views_create: str = 'views.create'
    views_change: str = 'views.change'
    views_delete: str = 'views.delete'


all_permissions = AllPermissions()
# 单例实例：全站统一通过 all_permissions.training_view 等访问权限点字符串。
# 字段默认值即权限点值，实例化时不需要传参。
# 用 pydantic 模型而非普通常量类的好处：字段名/值有类型约束，IDE 可补全，
# 误写字段名（如 all_permissions.training_vew）在实例化时直接报 ValidationError。


class ViewClassPermission(BaseModel):
    # "按 HTTP 方法声明权限"的载体：视图类属性
    #   permission_required = ViewClassPermission(GET=..., POST=...)
    # 每个字段默认 None = 该方法不要求特定权限点。
    GET: Optional[str] = None
    PATCH: Optional[str] = None
    PUT: Optional[str] = None
    DELETE: Optional[str] = None
    POST: Optional[str] = None
    # 五个字段覆盖本项目的写方法集合（没有 HEAD/OPTIONS——它们走安全方法默认放行）。
    # ※ 再次强调（README §4）：本代码库中没有 DRF 钩子读取这个类属性，
    #   它是"权限意图的自文档化声明"（上游 Label Studio 的惯例），
    #   真正的拦截由默认权限类 + queryset/perform_create 组织校验完成。


def make_perm(name, pred, overwrite=False):
    # 幂等地注册一个 rules 权限：
    if rules.perm_exists(name):
        # 同名权限已注册：
        if overwrite:
            rules.remove_perm(name)
            # overwrite=True：先删旧的再重新注册（本文件没用到这个分支）。
        else:
            return
            # 默认（overwrite=False）：直接返回，保留旧注册 → 重复 import 不会报错。
    rules.add_perm(name, pred)
    # 注册"权限名 name → 判定谓词 pred"。
    # 谓词签名：pred(subject, *args, **kwargs) → bool，subject 通常是 user。


for _, permission_name in all_permissions:
    make_perm(permission_name, rules.is_authenticated)
# ★ 模块级循环（import 本模块时执行一次，随 Django 启动）：
# - 遍历 all_permissions 的全部字段（pydantic 迭代 (字段名, 值) 对，_ 丢弃字段名），
#   把每个权限点字符串注册进 rules 库；
# - 谓词统一是 rules.is_authenticated：即"该权限对任何已登录用户都成立"。
# 效果：rules.has_permission('training.view', some_logged_in_user) → True，匿名 → False。
# ※ 但注意：经全库检索，本裁剪版代码中没有任何地方调用 rules.has_permission
#   （上游 Label Studio 的执行链路在这里被裁剪了），所以这段注册目前只起
#   "注册表完整性"的作用；权限点字符串的实际消费点是各视图的
#   permission_required 声明（声明式，见上）与未来可能的细粒度授权扩展。
