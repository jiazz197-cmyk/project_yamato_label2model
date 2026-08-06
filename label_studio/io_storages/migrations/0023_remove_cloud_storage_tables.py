"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license.
"""
# Generated manually — remove cloud storage tables (S3, GCS, AzureBlob import/export + links)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('io_storages', '0022_normalize_localfiles_paths'),
    ]

    operations = [
        migrations.DeleteModel(name='S3ImportStorage'),
        migrations.DeleteModel(name='S3ImportStorageLink'),
        migrations.DeleteModel(name='S3ExportStorage'),
        migrations.DeleteModel(name='S3ExportStorageLink'),
        migrations.DeleteModel(name='GCSImportStorage'),
        migrations.DeleteModel(name='GCSImportStorageLink'),
        migrations.DeleteModel(name='GCSExportStorage'),
        migrations.DeleteModel(name='GCSExportStorageLink'),
        migrations.DeleteModel(name='AzureBlobImportStorage'),
        migrations.DeleteModel(name='AzureBlobImportStorageLink'),
        migrations.DeleteModel(name='AzureBlobExportStorage'),
        migrations.DeleteModel(name='AzureBlobExportStorageLink'),
    ]