import factory
from core.utils.common import load_func
from django.conf import settings
from io_storages.base_models import ImportStorage, ProjectStorageMixin
from io_storages.models import RedisImportStorage


class StorageFactory(factory.django.DjangoModelFactory):
    title = factory.Faker('bs')
    description = factory.Faker('paragraph')

    class Meta:
        model = ImportStorage
        abstract = True


class ImportStorageFactory(StorageFactory):
    class Meta:
        model = ImportStorage
        abstract = True


class ProjectStorageMixinFactory(factory.django.DjangoModelFactory):
    project = factory.SubFactory(load_func(settings.PROJECT_FACTORY))

    class Meta:
        model = ProjectStorageMixin
        abstract = True


class RedisStorageMixinFactory(factory.django.DjangoModelFactory):
    class Meta:
        abstract = True


class RedisImportStorageBaseFactory(RedisStorageMixinFactory, ImportStorageFactory):
    class Meta:
        model = RedisImportStorage
        abstract = True


class RedisImportStorageFactory(RedisImportStorageBaseFactory, ProjectStorageMixinFactory):
    class Meta:
        model = RedisImportStorage
