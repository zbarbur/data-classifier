# Stream C: Model Registry + Lazy Loading

## Items
1. Model registry + lazy loading (P1, M)

## Files Modified/Created
- `data_classifier/registry/__init__.py` — NEW: ModelRegistry class + public API
- `data_classifier/registry/model_entry.py` — NEW: ModelEntry dataclass
- `data_classifier/engines/interface.py` — add `classify_batch()` default method
- `pyproject.toml` — add `[ml]` optional dependency extra
- `tests/test_model_registry.py` — NEW: registry tests with mock models
- `data_classifier/__init__.py` — export registry if needed

## Design

### ModelEntry Dataclass

```python
@dataclass
class ModelEntry:
    name: str                           # e.g. "gliner2-205m"
    loader: Callable[[], Any]          # factory function that loads the model
    model_class: str                    # e.g. "gliner2.GLiNER" for error messages
    requires: list[str] = field(default_factory=list)  # e.g. ["torch", "gliner"]
    _instance: Any = field(default=None, repr=False)
    _loaded: bool = field(default=False, repr=False)
```

### ModelRegistry Class

```python
class ModelRegistry:
    """Singleton registry for ML models with lazy loading and shared instances."""
    
    _entries: dict[str, ModelEntry]     # name -> entry
    
    def register(name, loader, model_class, requires=None) -> None
    def get(name) -> Any               # lazy-loads on first call, returns cached
    def is_loaded(name) -> bool
    def unload(name) -> None            # release memory
    def unload_all() -> None
    def list_registered() -> list[str]
    def check_dependencies(name) -> tuple[bool, list[str]]  # check if deps installed
```

### Key Design Decisions

1. **Singleton pattern**: One global registry via module-level instance. Engines register their models at import time. `get()` returns the same instance every time.

2. **Lazy loading**: `get()` calls `loader()` on first access. The loader function is provided at registration time. This means importing `data_classifier` never triggers model downloads.

3. **Dependency guards**: `check_dependencies()` uses `importlib.util.find_spec()` to check if required packages exist before attempting load. `get()` raises `ModelDependencyError` (custom exception) with a clear message: "Model 'gliner2-205m' requires packages: torch, gliner. Install with: pip install data_classifier[ml]"

4. **Thread safety**: Use `threading.Lock` per entry for concurrent access. Multiple engines might call `get()` simultaneously.

## Implementation Order

### Step 1: Create `data_classifier/registry/model_entry.py`

Simple dataclass with the fields above. Include `ModelDependencyError` exception class here.

### Step 2: Create `data_classifier/registry/__init__.py`

1. `ModelRegistry` class with all methods
2. Module-level `_default_registry` instance
3. Convenience functions: `register_model()`, `get_model()`, `check_model_deps()` that delegate to the default registry
4. Import guards using `importlib.util.find_spec()`
5. Thread-safe lazy loading with per-entry locks

### Step 3: Update `data_classifier/engines/interface.py`

Add `classify_batch()` method to `ClassificationEngine`:

```python
def classify_batch(
    self,
    columns: list[ColumnInput],
    *,
    profile: ClassificationProfile | None = None,
    min_confidence: float = 0.5,
    mask_samples: bool = False,
    max_evidence_samples: int = 5,
) -> list[list[ClassificationFinding]]:
    """Classify multiple columns in a batch.
    
    Default implementation delegates to classify_column() in a loop.
    ML engines should override this for efficient batched inference.
    """
    return [
        self.classify_column(
            col, profile=profile, min_confidence=min_confidence,
            mask_samples=mask_samples, max_evidence_samples=max_evidence_samples,
        )
        for col in columns
    ]
```

This is a non-breaking addition — all existing engines inherit the default loop behavior. ML engines override for GPU batching.

### Step 4: Update `pyproject.toml`

Add optional dependency group:

```toml
[project.optional-dependencies]
ml = [
    "torch>=2.0",
    "transformers>=4.40",
    "tokenizers>=0.19",
    "gliner>=0.2",
]
dev = [
    # ... existing dev deps ...
]
```

Also add to `package-data` if registry needs config files.

### Step 5: Write Tests (`tests/test_model_registry.py`)

1. **Registration:**
   - Register a mock model loader → appears in `list_registered()`
   - Register duplicate name → raises error

2. **Lazy loading:**
   - Register model → `is_loaded()` returns False
   - Call `get()` → loader called exactly once, `is_loaded()` returns True
   - Call `get()` again → same instance returned, loader NOT called again

3. **Dependency check:**
   - Register model requiring "nonexistent_package" → `check_dependencies()` returns (False, ["nonexistent_package"])
   - Call `get()` → raises `ModelDependencyError` with clear message
   - Register model requiring "json" (stdlib) → `check_dependencies()` returns (True, [])

4. **Unload:**
   - Load model → unload → `is_loaded()` returns False
   - `get()` after unload → re-loads

5. **classify_batch default:**
   - Create a concrete engine subclass with mock `classify_column`
   - Call `classify_batch` with 3 columns → returns 3 result lists
   - Verify `classify_column` called 3 times

6. **No ML deps required for tests:**
   - All tests use mock loaders (lambda returning simple objects)
   - No torch/transformers imports anywhere in tests

## Acceptance Criteria Verification
After all changes:
- `pytest tests/ -v` — all green (no ML deps needed)
- `ruff check . --exclude .claude/worktrees && ruff format --check . --exclude .claude/worktrees` — clean
- `python -c "from data_classifier.registry import register_model, get_model"` — import works
- `python -c "from data_classifier.engines.interface import ClassificationEngine; print(hasattr(ClassificationEngine, 'classify_batch'))"` — True
