# IO Storages

> **Note**: Cloud storage providers (S3, GCS, Azure Blob) have been removed from this project. Only `localfiles` and `redis` storage backends remain.

The `io_storages` app provides import and export storage backends for tasks and annotations. Two storage types are supported:

1. **Import Storage** (Source): Imports tasks from an external source into a project.
2. **Export Storage** (Target): Exports annotations from a project to an external destination.

## Available Backends

### Localfiles

Reads task data from the server's local filesystem and writes annotations back to disk.

**Import**: Scans a directory on the server, creates tasks from files. Two modes:
- `use_blob_urls=True`: Each file becomes a task with a URL pointing to `/data/local-files/?d=<path>`. Useful for images, audio, video.
- `use_blob_urls=False`: Reads `.json`/`.jsonl` files as task definitions.

**Export**: Writes completed annotations as JSON files to a target directory. Files are named `<annotation_id>.json`.

**Configuration**: Requires `LOCAL_FILES_SERVING_ENABLED=true` and `LOCAL_FILES_DOCUMENT_ROOT` set. All storage paths must be subdirectories of `LOCAL_FILES_DOCUMENT_ROOT`.

**Key models**: `LocalFilesImportStorage`, `LocalFilesExportStorage`, `LocalFilesImportStorageLink`, `LocalFilesExportStorageLink`.

### Redis

Reads task data from a Redis instance and writes annotations back to Redis.

**Import**: Scans Redis keys matching a prefix pattern, reads values as JSON task definitions. Supports custom host, port, and password.

**Export**: Writes serialized annotations as JSON strings to Redis keys. Uses a separate Redis database (default: db=2).

**Key models**: `RedisImportStorage`, `RedisExportStorage`, `RedisImportStorageLink`, `RedisExportStorageLink`.

## Base Architecture

Both backends inherit from the same abstract base classes in `base_models.py`:

| Base Class | Purpose |
|-----------|---------|
| `Storage` / `StorageInfo` | Status tracking, sync progress, validation contract |
| `ImportStorage` | Source storage: `iter_objects()`, `get_data()`, `scan_and_create_links()` |
| `ExportStorage` | Target storage: `save_annotation()`, `save_annotations()`, threaded export |
| `ImportStorageLink` | 1:1 link between tasks and their source objects |
| `ExportStorageLink` | Link between annotations and their exported files |
| `ProjectStorageMixin` | Project FK and permission checks |

## Sync Status Lifecycle

Storages track sync progress through status states:

```
Initialized → Queued → In Progress → Completed
                             ↓
                          Failed
```

When Redis is available, sync jobs run asynchronously via RQ workers. When Redis is unavailable, sync runs synchronously in-process.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/storages/localfiles/` | GET, POST | List/create localfiles import storages |
| `/api/storages/localfiles/{id}/sync` | POST | Trigger localfiles import sync |
| `/api/storages/export/localfiles/` | GET, POST | List/create localfiles export storages |
| `/api/storages/redis/` | GET, POST | List/create redis import storages |
| `/api/storages/redis/{id}/sync` | POST | Trigger redis import sync |
| `/api/storages/export/redis/` | GET, POST | List/create redis export storages |
| `/data/local-files/?d={path}` | GET | Serve local file content (not a REST endpoint) |

## Directory Structure

```
io_storages/
├── base_models.py      # Abstract base classes (Storage, ImportStorage, ExportStorage, links)
├── models.py           # App-level imports
├── localfiles/
│   ├── models.py       # LocalFilesImportStorage, LocalFilesExportStorage
│   ├── api.py          # REST API views
│   ├── serializers.py  # DRF serializers
│   ├── views.py        # /data/local-files/ file serving endpoint
│   └── functions.py    # Path normalization helpers
├── redis/
│   ├── models.py       # RedisImportStorage, RedisExportStorage
│   ├── api.py          # REST API views
│   └── serializers.py  # DRF serializers
├── s3/                 # Removed — cloud storage provider
├── gcs/                # Removed — cloud storage provider
├── azure_blob/         # Removed — cloud storage provider
├── api.py              # Shared API utilities
├── proxy_api.py        # Storage proxy (retained for URI resolution)
└── utils.py            # Shared utilities (StorageObject, load_tasks_json)
```